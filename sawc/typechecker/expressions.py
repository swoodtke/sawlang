"""
Expression checking methods for the Saw type checker.

This module provides mixin methods for checking all expression types including
literals, operators, function calls, method calls, closures, and more.

Usage:
    class TypeChecker(ExpressionsMixin, ...):
        pass
"""

from typing import Optional, Dict, List, NamedTuple
from types import SimpleNamespace as _SandboxNode
from ast_nodes import (
    Expression, IntLiteral, FloatLiteral, BoolLiteral, StringLiteral,
    StringInterpolation, FormatPlaceholder,
    Identifier, BinaryOp, UnaryOp, MoveExpr, ReferenceExpr, CastExpr,
    FunctionCall, IfExpr, IfLetExpr, TupleLiteral, TupleIndex,
    ArrayLiteral, MapLiteral, SetLiteral, ArrayIndex, MemberAccess, StructInit, NoneLiteral,
    ForceUnwrap, NilCoalesce, OptionalChain, BindOptional, OptionalEvalExpr,
    OptionalChainAssign, MethodCall, SelfExpr,
    SourceLocationLiteral,
    EnumInit, MatchExpr, WhileExpr, RangeExpr, ForLoop, ClosureExpr,
    TryExpr, TryCatchExpr,
    Block, LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    CompoundAssignStatement, GuardLetStatement, BreakStatement,
    SawType, TypeKind, specialization_key,
    ResultOkWrap, ResultErrWrap, OptionalWrap,
    Pattern, WildcardPattern, BindingPattern, LiteralPattern,
    RangePattern, TuplePattern, EnumPattern,
    Argument, ASTNode, MatchArm, structural_fields,
)
from ast_walk import child_nodes
from noescape import first_reference_in
from errors import ErrorKind
from const_eval import const_eval, ConstEvalError, CONST_LENGTH_HINT
from namespace import Visibility, EnumSymbol
from type_identity import type_identity as _type_identity

# design 242: the IDENTITIES of `std.task`'s two thread handles, not their
# spellings. `Thread.spawn { … }` names no type at the source level — this pass
# mints the reference — so it must reach std's declaration whatever the module
# it lands in declares (a user `struct Thread` binds the spelling to its own
# identity, exactly as a user `struct Slot` does). Same rule and same mangling
# helper as the coroutine transform's `SLOT_STRUCT_NAME`.
THREAD_STRUCT_NAME = _type_identity("Thread", ("<std>", "task"))
VOID_THREAD_STRUCT_NAME = _type_identity("VoidThread", ("<std>", "task"))

# Sentinel: a length that IS a compile-time constant but whose value belongs to
# an instantiation rather than to this (abstract) pass — `[v; N]` inside a
# generic body (design 148). Distinct from None, which means "not constant".
_ABSTRACT_COUNT = object()


class _SpawnBorrow(NamedTuple):
    """One root a `group.spawn(...)` borrows for its task's life.

    Produced by `ExpressionsMixin._spawn_borrow_sources`, which is the single
    place that knows WHERE a spawned task can take a reference to its spawner.
    `key` identifies the source so the order check can hand back what it refused;
    `kind` is `'capture'` or `'argument'` and drives nothing but the wording.
    """
    key: int
    kind: str
    name: str
    mutable: bool
    line: int
    column: int

    @property
    def sigil(self) -> str:
        return "&var" if self.mutable else "&"


def _moved_names(node, out=None):
    """Every name a `move` under `node` consumes.

    The one thing a BORROW capture cannot serve (DF-218h): `move` out of a
    reference is not a transfer the language has. Such a name is spelled
    `[move x]` instead, which for a non-escaping closure is the deferred
    transfer — the body takes the value when it runs. Used by
    `_synthesize_place_window_captures`.
    """
    if out is None:
        out = set()
    if node is None:
        return out
    if isinstance(node, MoveExpr) and getattr(node, 'variable', None):
        out.add(node.variable)
    for child in child_nodes(node):
        _moved_names(child, out)
    return out


class ExpressionsMixin:
    """Mixin providing expression checking methods for TypeChecker."""

    def _check_expression(self, expr: Expression) -> Optional[SawType]:
        """Check an expression and return its type.

        This is the single chokepoint through which every expression is
        checked. It stamps the computed type onto ``expr.resolved_type`` so
        codegen can consume it (see ``CodeGenerator._expr_type``) instead of
        re-inferring types with a weaker, divergent engine.

        Ordering rule -- "later contextual annotation wins": a few callers
        annotate *contextually* after this returns (e.g.
        ``_propagate_optional_type`` pushes an expected optional type down into
        ``None`` literals). Those run after the child's ``_check_expression``
        has already returned and stamped here, so their more-specific
        annotation overwrites the generic one stamped below. Never re-check a
        node after contextually annotating it, or the generic stamp would win.

        An unknown node RAISES (design 192 unit 1), the way codegen's twin
        dispatch (``CodeGenerator._generate_expression``) always has. It used to
        ``return None``, so a node type nobody had taught the checker about went
        unchecked and unannotated in silence and the damage surfaced far away —
        in codegen, as a missing ``resolved_type`` — or not at all. What the
        flush found: ``ErasedErrWrap``, which the checker INSERTS into the AST
        and then re-visits on the design-146 second pass; its three siblings
        (``visit_ResultOkWrap`` and below) carry the re-check visitor and it did
        not (DF-192a).
        """
        # design 192 unit 2: the breadcrumb. The typechecker was ENTIRELY
        # unwrapped until this brief — every internal failure in it printed a
        # raw Python traceback — and this is what its new wrapper
        # (`sawc.run_typecheck`) reads to anchor the report. Two dispatches stamp
        # it, here and `_check_statement`; see `sawc._ice_location`. Restored
        # only on the SUCCESS path, deliberately: an exception leaves the
        # INNERMOST node being checked stamped, which is the one the report
        # wants to name, while a finished sub-expression hands the slot back.
        old_node = getattr(self, '_current_node', None)
        self._current_node = expr

        # design 210: this subtree already has its answers. Hand them back
        # instead of asking the entry module's namespace a question the callee's
        # namespace answered at the declaration.
        # `getattr`: a `ForLoop` is a Statement that also arrives here (a
        # for-loop in expression position), so the field is not universal.
        if getattr(expr, 'embed_preserved', False) and expr.resolved_type is not None:
            result = self._check_preserved_embed(expr)
            self._current_node = old_node
            return result

        method_name = f'visit_{expr.__class__.__name__}'
        visitor = getattr(self, method_name, None)
        if visitor is None:
            raise ValueError(f"Unknown expression type: {type(expr)}")
        result = visitor(expr)
        if result is not None:
            expr.resolved_type = result
            # design 130 rule 3: an expression whose VALUE has an unsafe type is
            # the function naming/binding one. A closure literal is skipped —
            # `_check_closure` decides which domain its body's contact belongs to
            # (design 136), and its own function type names the unsafe parameter
            # by construction, which the slot it is passed to already declares.
            if not isinstance(expr, ClosureExpr):
                self._note_unsafe_contact(
                    result, expr, "its body names a value of unsafe type")
            # design 149 unit d: on a target with no atomic instruction, naming a
            # `SpinLock` is refused. Guarded on the target so the ordinary case
            # is one boolean test.
            if not self._atomics_native:
                self._check_spinlock_target(result, expr)
        self._current_node = old_node
        return result

    def _check_preserved_embed(self, expr: Expression) -> Optional[SawType]:
        """Answer for a subtree the coroutine transform spliced in UNCHANGED.

        Design 210, the non-generic path. An embed splices a callee's
        already-checked body into the ENTRY module's AST, and the post-transform
        pass then re-checks that AST under the entry module's namespace. Every
        question this subtree could be asked was answered once already, in the
        CALLEE's namespace — which is where its module-private siblings are
        names. Re-asking is not a safety net, it is a different question: it is
        what made `builder.Builder.build`, embedded into blade's `main`, report
        `function `resolve` is not directly accessible` about a call in
        `builder`'s own file (DF-206e).

        So the mark says "the answers travel with the node", and this returns
        the stored `resolved_type` without re-resolving anything. What the
        contract covers — resolved types, resolved callee symbols, effect facts,
        place/copy judgments — is enumerated in `THE EMBED CONTRACT` at the top
        of `coro_transform.py`, and closed by the astgraft gate.

        THE WHOLE SUBTREE IS SKIPPED, not just this node. A preserved subtree is
        closed: every node in it was resolved together, and descending would
        re-ask questions about nodes that were never independently askable —
        a module QUALIFIER (`builder.Builder(...)`) is an `Identifier` its parent
        resolves as part of one qualified name, so checking it alone reports
        `undefined variable `builder``, which is how blade failed when this
        descended.

        GLUE IS STILL TYPED, and that is what makes the wholesale skip safe: the
        transform stamps its OWN rewrites where it makes them — a frame-slot read
        takes the type of the local it replaces (`_read_field`), an ANF temp the
        type of the call it hoists — so a graft inside a preserved subtree
        arrives already answered rather than needing this pass. Everything the
        transform builds AROUND the body — the state dispatch, the resumption
        edges, the frame init — is a new unmarked node and is checked here
        normally. `_assert_embed_closed` is the tripwire on the invariant.

        THE ONE DESCENT (design 218 stage 1). A frame-slot READ is the graft
        that cannot arrive pre-answered: `self.x.value()` is a `borrows`
        accessor, and an accessor becomes a window call only after this pass
        stamps `place_struct` on it, so skipping it leaves a call codegen has
        never heard of. It is also the graft that does not NEED to be
        pre-answered — it names the frame struct's own field and a public
        method of `std.compiler.frame`, so the entry module's namespace answers
        it exactly as the callee's would. The transform says so with
        `frame_slot_op`.

        The place lowering then rewrites those reads, and its output inherits
        the same standing: a `value()` chain becomes a `__window` call carrying
        the rest of the chain in a closure, and the closure's parameter type is
        derived from the accessor's signature by THIS pass. Un-marked
        `place_lowered` output inside a preserved subtree is by construction
        the post-transform lowering's own (anything lowered before the
        transform was marked with everything else the declaration pass
        resolved), and it is namespace-neutral for the same reason the read
        was. So the descent covers both, and asks nothing else in the subtree
        anything.
        """
        self._check_embedded_grafts(expr)
        return expr.resolved_type

    @staticmethod
    def _is_embedded_graft(node) -> bool:
        """Whether `node` inside a preserved subtree is a graft this pass owes
        an answer — a transform slot read, or the place lowering's rewrite of
        one."""
        if getattr(node, 'frame_slot_op', False):
            return True
        return (getattr(node, 'place_lowered', False)
                and not getattr(node, 'embed_preserved', False))

    def _check_embedded_grafts(self, expr) -> None:
        """Check the grafts inside a preserved subtree.

        The walk does not descend THROUGH a graft: its receiver, arguments and
        (for a window) the rest of the chain are covered by checking it, and
        the preserved nodes it carries short-circuit on their own.
        """
        for sub in child_nodes(expr):
            if self._is_embedded_graft(sub):
                self._check_expression(sub)
            else:
                self._check_embedded_grafts(sub)

    # ===== Expression Visitor Methods =====

    # Design 53: a suffixed integer literal IS its fixed-width type.
    _SUFFIX_TYPE_KINDS = {
        'i8': TypeKind.INT8, 'i16': TypeKind.INT16,
        'i32': TypeKind.INT32, 'i64': TypeKind.INT64,
        'u8': TypeKind.UINT8, 'u16': TypeKind.UINT16,
        'u32': TypeKind.UINT32, 'u64': TypeKind.UINT64,
    }

    # Design 53: type names carrying `.max`/`.min` integer limits → their kind.
    _INT_LIMIT_TYPE_KINDS = {
        'Int': TypeKind.INT, 'UInt': TypeKind.UINT,
        'Int8': TypeKind.INT8, 'Int16': TypeKind.INT16,
        'Int32': TypeKind.INT32, 'Int64': TypeKind.INT64,
        'UInt8': TypeKind.UINT8, 'UInt16': TypeKind.UINT16,
        'UInt32': TypeKind.UINT32, 'UInt64': TypeKind.UINT64,
    }

    def _check_alias_construction(self, expr, alias_info) -> Optional[SawType]:
        """`UserId(42)` — build a value of a distinct `type` alias (design 63).

        The flow rule is deliberately one-way: an alias value projects toward
        its underlying freely (implicitly, or with `as`), and nothing flows
        back on its own. This is the sanctioned way back, and that it is a
        CONSTRUCTION rather than a cast is the whole point — `42 as UserId` is
        an error precisely because widening authority over a value should read
        as making one, at the site that makes it.

        The argument is checked against the underlying type with that type
        pushed down as the expectation, so a bare literal adopts it and is
        range-checked there (design 87). That is what makes an alias over a
        FIXED-WIDTH underlying constructible at all: `type Handle = UInt` had
        no spelling before this, since an annotated `let` only accepts an
        underlying that is one of the four primitive kinds.

        Representationally this is a no-op — an alias IS its underlying — so
        codegen compiles the operand and nothing else.
        """
        if len(expr.arguments) != 1:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{expr.name}` is a type alias and is constructed from "
                f"exactly one value, but {len(expr.arguments)} were given",
                expr.line, expr.column,
                hint=f"write `{expr.name}(<{self._resolve_type_alias(SawType(TypeKind.STRUCT, struct_name=expr.name))}>)`"
            )
            return None
        arg = expr.arguments[0]
        if arg.name:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{expr.name}` is a type alias and takes one unlabeled value, "
                f"but the argument is labeled `{arg.name}`",
                arg.value.line, arg.value.column,
                hint="a type alias has no fields to name — drop the label"
            )
            return None

        # DF-229b: by the design-144 IDENTITY, not the spelling. Every
        # annotation naming this alias was rewritten to the identity by
        # `_canonicalize_module_types`, so a type built from the spelling
        # compares unequal to the very annotation it is being assigned to —
        # `let s: Steps = Steps(n)` inside any non-root module was "cannot
        # assign `Steps` to variable of type `Steps`". Spelling and identity
        # coincide in a root module, which is why the single-file form worked.
        alias_name = self._canonical_type_name(expr.name)
        alias_type = SawType(TypeKind.STRUCT, struct_name=alias_name)
        underlying = self._resolve_type_alias(alias_type)
        # design 188 unit 1 (DF-188b, audit R50): the back-conversion is what
        # INHABITS an alias, so an alias over a reference is refused here too —
        # the value it builds is a reference living outside the parameter
        # position that created it, which is the whole no-escape rule.
        if self._first_laundered_reference(alias_type) is not None:
            self._reject_laundered_reference(
                alias_type, f"a value of type `{expr.name}`",
                expr.line, expr.column)
            return None
        self._apply_literal_expected_type(arg.value, underlying)
        arg_type = self._check_expression(arg.value)
        if arg_type is None:
            return None
        # The value must be one the underlying accepts. `allow_literal_to_distinct`
        # is NOT passed: the operand is being converted to the underlying here,
        # not to another alias, so the ordinary rule is the right one.
        if not self._transfer_compatible(arg_type, underlying):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{expr.name}` is a type alias for `{underlying}` and cannot "
                f"be built from `{arg_type}`",
                arg.value.line, arg.value.column,
                hint=self._int_conversion_hint(arg_type, underlying)
            )
            return None
        expr.alias_construction = alias_name
        return alias_type

    def _stamp_enum_raw_value(self, expr, enum_info) -> None:
        """Record a raw-backed enum case's tag value on the access node.

        A case of an enum that DECLARED a backing denotes a fixed number — that
        is what design 145 unit B2 means by pinning the values, and it is why
        `e as UInt8` is total. Recording it here is what lets the constant
        evaluator fold `SysOp.Shutdown as UInt`, so a `static_assert` can pin a
        wire table against the enum that defines it rather than against a
        transcribed copy of its numbers.

        An UNBACKED enum stamps nothing: its ordinals are the compiler's
        business and reordering its cases must stay a free edit, so its cases
        are deliberately not constants anything may read.
        """
        raw_values = getattr(enum_info, 'raw_values', None)
        if raw_values:
            value = raw_values.get(expr.member)
            if value is not None:
                expr.enum_raw_value = value

    def visit_IntLiteral(self, expr: IntLiteral) -> Optional[SawType]:
        suffix = getattr(expr, 'suffix', None)
        if suffix is not None:
            return SawType(self._SUFFIX_TYPE_KINDS[suffix])
        # Design 87: a bare integer literal that flows into a FIXED-WIDTH slot
        # adopts that type. The expectation (and the range check) is pushed down
        # by the central `_apply_literal_expected_type` propagation
        # (let/param/field/return/compound-assign/collection/tuple/if-match-arm),
        # so this ONE site types the literal uniformly at every position.
        #
        # Design 205: a platform `UInt` expectation is adopted too. The
        # propagation funnel has STAMPED one since DF-137d (`_int_range_for`
        # answers the INT/UINT target width), but this site honoured
        # `_FIXED_INT_RANGES` only and fell back to `Int` — and the platform-pair
        # permission in `_types_compatible` silently absorbed the `Int`/`UInt`
        # mismatch that left behind. With that permission gone the mismatch is
        # real, so `var acc: UInt = 0` and `static MASK: UInt = 255` have to type
        # their literal at the width the slot named. No integer expectation at
        # all still means platform `Int` — the load-bearing invariant, so
        # `let x = 5` and `Int`/`Int` arithmetic are unchanged.
        expected = getattr(expr, 'expected_type', None)
        if expected is not None:
            rt = self._resolve_type(expected)
            if rt is not None and (rt.kind in self._FIXED_INT_RANGES
                                   or rt.kind in self._PLATFORM_INT_KINDS):
                return SawType(rt.kind)
        return SawType(TypeKind.INT)

    def visit_FloatLiteral(self, expr: FloatLiteral) -> Optional[SawType]:
        return SawType(TypeKind.FLOAT)

    def visit_BoolLiteral(self, expr: BoolLiteral) -> Optional[SawType]:
        return SawType(TypeKind.BOOL)

    def visit_StringLiteral(self, expr: StringLiteral) -> Optional[SawType]:
        return SawType(TypeKind.STRING)

    def visit_SourceLocationLiteral(self, expr: SourceLocationLiteral) -> Optional[SawType]:
        """Resolve a `#file` / `#line` / `#function` literal at its DEFINITION
        site (design 98). Filled exactly ONCE and frozen — a second visit (the
        post-coroutine-transform re-check, where `current_function`/`current_
        method` may be a synthesized frame method) must NOT re-resolve, so
        `#line`/`#function` inside a suspending body report the ORIGINAL source,
        not the transformed frame's line/name."""
        import os
        if expr.resolved_kind is None:
            if expr.kind == 'line':
                expr.resolved_kind = 'int'
                expr.resolved_int = getattr(expr, 'line', 0) or 0
            elif expr.kind == 'file':
                expr.resolved_kind = 'string'
                expr.resolved_str = self._source_location_file(expr)
            else:  # 'function'
                expr.resolved_kind = 'string'
                expr.resolved_str = self._source_location_function()
        return SawType(TypeKind.INT if expr.resolved_kind == 'int'
                       else TypeKind.STRING)

    def visit_LendVarLiteral(self, expr) -> Optional[SawType]:
        """The `#lend_var` scope fence (design 179).

        Every LEGAL occurrence is folded away before the checker runs: the
        place transform duplicates a `borrows` body that names the constant and
        folds it per specialization, pruning the branch it decides. So anything
        that reaches here is, by construction, misplaced — and this visitor
        never has to ask where it is.

        It still types `Bool`, so a body that misuses it gets ONE diagnostic
        rather than a cascade from an unknown-typed condition."""
        from errors import ErrorKind
        self._error(
            ErrorKind.TYPE_MISMATCH,
            "`#lend_var` is legal only inside a `borrows` body — it names the "
            "SPECIALIZATION the compiler is building (`false` for the shared "
            "window, `true` for the exclusive one), and a declaration that "
            "lends no place has no specializations",
            expr.line, expr.column,
            hint="declare the accessor `func name(&self, ...) borrows -> T` if "
                 "it means to lend a place; a runtime condition is an ordinary "
                 "`Bool` expression")
        return SawType(TypeKind.BOOL)

    def _source_location_file(self, expr: SourceLocationLiteral) -> str:
        """The source BASENAME for `#file` — matches the design-69 panic prefix
        (`os.path.basename` of the file the token appears in). Falls back to the
        enclosing declaration's file, then the entry file."""
        import os
        src = getattr(expr, 'source_file', None) or self._get_current_source_file()
        if not src:
            src = getattr(self, '_di_source_path', None) or \
                getattr(getattr(self, 'reporter', None), 'source_path', None)
        return os.path.basename(src) if src else "<unknown>.saw"

    def _source_location_function(self) -> str:
        """The bare enclosing function/method name for `#function` (design 98):
        `method.name` (e.g. `mag`, `init`) with NO struct qualifier, or the free
        function name (`main`); module scope -> `<module>`."""
        if self.current_method is not None:
            return getattr(self.current_method, 'name', None) or "<module>"
        if self.current_function is not None:
            return getattr(self.current_function, 'name', None) or "<module>"
        return "<module>"

    # The types `print` and string interpolation render without a `Printable`
    # conformance. Everything else has to have one; design 132 unit D routes both
    # sites through `_check_renderable_operand` so they agree.
    _RENDERABLE_BUILTIN_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT, TypeKind.FLOAT, TypeKind.BOOL, TypeKind.STRING,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
    })

    # The platform-width integer pair, for the overload-ranking signedness
    # tiebreak below.
    _PLATFORM_INT_KINDS = frozenset({TypeKind.INT, TypeKind.UINT})

    def _check_renderable_operand(self, expr_type, sub_expr, verb: str,
                                  where: str = "") -> bool:
        """Whether a value of `expr_type` can be rendered, reporting if not.

        `print(o)` on an `Int?` used to reach codegen and die there with
        `internal compiler error: Cannot print type: {i1, i64}`, while
        interpolating the same value already gave the clean not-`Printable`
        error (DF-128d / DF-129a, found independently by two agents). Both
        callers now ask the same question, so `print(v.get(0))` — the easy way
        to meet this by accident, since `Vector.get` returns `T?` — is a
        diagnostic rather than a crash.
        """
        if expr_type.kind in self._RENDERABLE_BUILTIN_KINDS:
            return True
        # A `T: Printable` bound satisfies this inside a generic body.
        if self._bound_satisfied(expr_type, "Printable"):
            return True
        # An OPTIONAL cannot be conformed (DF-174d's adjacent nit): `extension
        # Int?: Printable` is not writable — `Int?` is not a nominal type, and
        # the orphan rule would forbid it even if it were. Name what actually
        # works instead of advice the reader would spend a while failing at.
        if expr_type.kind == TypeKind.OPTIONAL:
            hint = ("unwrap it first — `if let v = o` / `o ?? <fallback>` — "
                    "since an optional cannot be given a `Printable` "
                    "conformance of its own")
        else:
            hint = (f"conform it with `extension "
                    f"{self._type_display_name(expr_type)}: Printable {{ ... }}`")
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{verb} value of type `{expr_type}`{where}: it is not `Printable`",
            getattr(sub_expr, 'line', 0), getattr(sub_expr, 'column', 0),
            hint=hint)
        return False

    def visit_StringInterpolation(self, expr: StringInterpolation) -> Optional[SawType]:
        """Type check string interpolation expressions (design 56).

        Builtin types (integers, Float, Bool, String) keep the existing fast
        lowering. Any other type must be Printable: it is streamed into the
        interpolation builder via its `format`/`to_string`. A non-Printable type
        is a clean error naming the type and the trait."""
        for sub_expr in expr.expressions:
            # design 137: an empty `{}` is a FORMAT PLACEHOLDER, filled from a
            # call's argument list. Reaching here means the string is not the
            # format argument of one, so there is no value to put in it.
            if isinstance(sub_expr, FormatPlaceholder):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "`{}` is a format placeholder and needs an argument to fill it",
                    sub_expr.line, sub_expr.column,
                    hint="pass a value for it — `print(\"x = {}\", x)` — or name "
                         "the value in the braces (`\"x = {x}\"`); write `\\{\\}` "
                         "for literal braces")
                return None
            expr_type = self._check_expression(sub_expr)
            if expr_type is None:
                return None
            if not self._check_renderable_operand(
                    expr_type, sub_expr, "cannot interpolate", " in a string"):
                return None
        # design 135: interpolation builds a fresh heap String out of pieces the
        # source never asked to store. The ban is uniform — a `panic`/`assert`
        # message is no exception, because the allocator being out is exactly
        # when a panic has to work.
        if expr.expressions and self._hidden_alloc_gate():
            self._hidden_alloc_error(
                "string interpolation allocates a String",
                expr.line, expr.column,
                hint="pass the values as format arguments instead — "
                     "`print(\"x = {}\", x)`, `panic(\"out of {}\", what)` — or "
                     "assemble the text in a fixed-capacity `StringBuilder`; a "
                     "message with nothing interpolated into it is an interned "
                     "literal and costs nothing")
        return SawType(TypeKind.STRING)

    def _format_placeholder_count(self, fmt_expr):
        """How many `{}` slots a format-string argument has, or None if the
        expression cannot be one.

        A plain `StringLiteral` has none (it is a complete message). A
        `StringInterpolation` may carry placeholders, real `{expr}` pieces, or
        both — the caller decides what to allow. Anything else (a String-typed
        variable, a call result) is not a format string: its placeholders could
        not be counted at compile time, which is the whole point of checking
        arity here rather than at runtime.
        """
        if isinstance(fmt_expr, StringLiteral):
            return 0
        if isinstance(fmt_expr, StringInterpolation):
            return sum(1 for e in fmt_expr.expressions
                       if isinstance(e, FormatPlaceholder))
        return None

    def _check_format_call(self, name: str, expr, value_args,
                           fmt_index: int = 0) -> None:
        """Check a `print`/`panic`/`assert` call that supplies format arguments.

        Design 137. The format string must be a LITERAL so `{}` slots can be
        counted at compile time: a mismatch between slots and arguments is an
        error here, never a runtime surprise, and there are no varargs to
        type-erase — each argument keeps its own type and is rendered through
        its own `Printable.format`. `fmt_index` is 1 for `assert`, whose Bool
        condition comes first.
        """
        fmt_expr = expr.arguments[fmt_index].value
        count = self._format_placeholder_count(fmt_expr)

        if count is None:
            self._check_expression(fmt_expr)
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{name}` with format arguments needs a literal format string",
                fmt_expr.line, fmt_expr.column,
                hint="the `{}` slots are counted at compile time, so the format "
                     "string cannot be a variable")
            for arg in value_args:
                self._check_expression(arg.value)
            return

        # Mixing a real `{expr}` interpolation into a format string would build
        # a heap String for the format string itself, which is exactly what this
        # path exists to avoid — and it reads ambiguously besides.
        if isinstance(fmt_expr, StringInterpolation):
            for piece in fmt_expr.expressions:
                if not isinstance(piece, FormatPlaceholder):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`{name}` format string mixes `{{...}}` interpolation "
                        f"with `{{}}` placeholders",
                        piece.line, piece.column,
                        hint="use `{}` for every slot and pass the values as "
                             "arguments; an interpolated format string would "
                             "allocate, which is what this spelling avoids")
                    for arg in value_args:
                        self._check_expression(arg.value)
                    return

        if count != len(value_args):
            slots = "1 placeholder" if count == 1 else f"{count} placeholders"
            given = ("1 argument" if len(value_args) == 1
                     else f"{len(value_args)} arguments")
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{name}` format string has {slots} but {given} "
                f"{'was' if len(value_args) == 1 else 'were'} given",
                expr.line, expr.column,
                hint="every `{}` takes exactly one argument, by position")

        for arg in value_args:
            if arg.name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`{name}` format arguments are positional and take no label",
                    arg.value.line, arg.value.column)
            arg_type = self._check_expression(arg.value)
            if arg_type is None:
                continue
            # A Float used to be refused here: the renderer was `snprintf`, and
            # freestanding has no libc. Design 253 made it Saw — integer
            # arithmetic over two read-only tables, written through a fixed
            # `StringBuilder` — so there is nothing left to refuse. (The refusal
            # was never at every position anyway: interpolation, `to_string()`
            # and `format(into:)` reached the same snprintf and were not gated,
            # so a freestanding object could carry an undefined `snprintf`.)
            self._check_renderable_operand(arg_type, arg.value, "cannot format")

    def _type_display_name(self, saw_type: SawType) -> str:
        """A bare type name for diagnostics (struct/enum name, else the type)."""
        if saw_type is None:
            return "T"
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            return saw_type.struct_name
        if saw_type.kind == TypeKind.ENUM and saw_type.enum_name:
            return saw_type.enum_name
        return str(saw_type)

    def visit_Identifier(self, expr: Identifier) -> Optional[SawType]:
        return self._check_identifier(expr)

    def visit_BinaryOp(self, expr: BinaryOp) -> Optional[SawType]:
        return self._check_binary_op(expr)

    def visit_UnaryOp(self, expr: UnaryOp) -> Optional[SawType]:
        return self._check_unary_op(expr)

    def visit_MoveExpr(self, expr: MoveExpr) -> Optional[SawType]:
        return self._check_move_expr(expr)

    def visit_ReferenceExpr(self, expr: ReferenceExpr) -> Optional[SawType]:
        return self._check_reference_expr(expr)

    def visit_CastExpr(self, expr: CastExpr) -> Optional[SawType]:
        return self._check_cast_expr(expr)

    def visit_ResultOkWrap(self, expr) -> Optional[SawType]:
        """Re-check an already-inserted Ok wrap (design 92).

        These wraps are synthesized during the FIRST typecheck, then the
        coroutine transform rewrites bare identifiers inside `expr.value` into
        fresh frame-field `MemberAccess` nodes that carry NO `resolved_type`. The
        pipeline re-typechecks the transformed AST, so this visitor MUST descend
        into `expr.value` to re-annotate it — without it a Result-returning
        suspending method that returns a frame-resident value (`return move buf`,
        `TcpStream(fd: cfd as Int32)`) reaches codegen with an unannotated node
        and ICEs."""
        if expr.value is not None:
            self._check_expression(expr.value)
        return getattr(expr, 'result_type', None)

    def visit_ResultErrWrap(self, expr) -> Optional[SawType]:
        """Re-check an already-inserted Err wrap — see visit_ResultOkWrap."""
        if expr.value is not None:
            self._check_expression(expr.value)
        return getattr(expr, 'result_type', None)

    def visit_ErasedErrWrap(self, expr) -> Optional[SawType]:
        """Re-check an already-inserted erased Err wrap — see visit_ResultOkWrap.

        DF-192a: the fourth sibling, and the only one that never got this
        visitor. Design 192 unit 1 made the unknown-node fallthrough raise, and
        this is what it flushed — the checker builds an ``ErasedErrWrap`` around
        a concrete error on the way out of an erased-Result function, writes it
        back into the AST (``func.body.final_expr`` / ``stmt.value``), and then
        walks that same AST again on the design-146 second pass. Without the
        visitor the wrap's inner value is never re-annotated after the coroutine
        transform has rewritten the identifiers inside it.
        """
        if expr.value is not None:
            self._check_expression(expr.value)
        return getattr(expr, 'result_type', None)

    def visit_OptionalWrap(self, expr) -> Optional[SawType]:
        """Re-check an already-inserted `T -> T?` wrap — see visit_ResultOkWrap.

        The Result wraps got this visitor when the coroutine transform started
        re-checking its own output; the optional wrap needs it for the same
        reason and had simply never been re-checked before. Without it the node
        types as None, which becomes `Void` at the nearest block tail — and a
        window closure whose tail wraps a place read (`{ __p in __p }` against
        `-> T?`) then arrives at the argument check as `(&var T) -> Void`."""
        if expr.value is not None:
            self._check_expression(expr.value)
        return getattr(expr, 'target_type', None)

    def visit_FunctionCall(self, expr: FunctionCall) -> Optional[SawType]:
        return self._check_function_call(expr)

    def visit_IfExpr(self, expr: IfExpr) -> Optional[SawType]:
        return self._check_if_expr(expr)

    def visit_IfLetExpr(self, expr: IfLetExpr) -> Optional[SawType]:
        return self._check_if_let_expr(expr)

    def visit_TupleLiteral(self, expr: TupleLiteral) -> Optional[SawType]:
        return self._check_tuple_literal(expr)

    def visit_TupleIndex(self, expr: TupleIndex) -> Optional[SawType]:
        return self._check_tuple_index(expr)

    def visit_ArrayLiteral(self, expr: ArrayLiteral) -> Optional[SawType]:
        return self._check_array_literal(expr)

    def visit_MapLiteral(self, expr: MapLiteral) -> Optional[SawType]:
        return self._check_map_literal(expr)

    def visit_SetLiteral(self, expr: SetLiteral) -> Optional[SawType]:
        return self._check_set_literal(expr)

    def visit_ArrayIndex(self, expr: ArrayIndex) -> Optional[SawType]:
        return self._check_array_index(expr)

    def visit_MemberAccess(self, expr: MemberAccess) -> Optional[SawType]:
        return self._check_member_access(expr)

    def visit_StructInit(self, expr: StructInit) -> Optional[SawType]:
        return self._check_struct_init(expr)

    def visit_NoneLiteral(self, expr: NoneLiteral) -> Optional[SawType]:
        return self._check_none_literal(expr)

    def visit_ForceUnwrap(self, expr: ForceUnwrap) -> Optional[SawType]:
        return self._check_force_unwrap(expr)

    def visit_NilCoalesce(self, expr: NilCoalesce) -> Optional[SawType]:
        return self._check_nil_coalesce(expr)

    def visit_OptionalChain(self, expr: OptionalChain) -> Optional[SawType]:
        return self._check_optional_chain(expr)

    def visit_BindOptional(self, expr: BindOptional) -> Optional[SawType]:
        return self._check_bind_optional(expr)

    def visit_OptionalEvalExpr(self, expr: OptionalEvalExpr) -> Optional[SawType]:
        return self._check_optional_eval(expr)

    def visit_OptionalChainAssign(self, expr: OptionalChainAssign) -> Optional[SawType]:
        return self._check_optional_chain_assign(expr)

    def visit_MethodCall(self, expr: MethodCall) -> Optional[SawType]:
        return self._check_method_call(expr)

    def visit_SelfExpr(self, expr: SelfExpr) -> Optional[SawType]:
        return self._check_self_expr(expr)

    def visit_EnumInit(self, expr: EnumInit) -> Optional[SawType]:
        return self._check_enum_init(expr)

    def visit_MatchExpr(self, expr: MatchExpr) -> Optional[SawType]:
        return self._check_match_expr(expr)

    def visit_WhileExpr(self, expr: WhileExpr) -> Optional[SawType]:
        return self._check_while_expr_as_expression(expr)

    def visit_RangeExpr(self, expr: RangeExpr) -> Optional[SawType]:
        return self._check_range_expr(expr)

    def visit_ForLoop(self, expr: ForLoop) -> Optional[SawType]:
        return self._check_for_loop_as_expression(expr)

    def visit_ClosureExpr(self, expr: ClosureExpr) -> Optional[SawType]:
        return self._check_closure(expr)

    def visit_TryExpr(self, expr: TryExpr) -> Optional[SawType]:
        return self._check_try_expr(expr)

    def visit_TryCatchExpr(self, expr: TryCatchExpr) -> Optional[SawType]:
        return self._check_try_catch_expr(expr)

    def _check_identifier(self, expr: Identifier) -> Optional[SawType]:
        """Check an identifier reference.

        For reference types (&T or &var T), this auto-dereferences and returns
        the inner type T. This provides implicit dereference semantics.
        """
        var_info = self.current_scope.lookup(expr.name)
        if not var_info:
            # A const generic parameter reads as a plain value of its declared
            # type (design 148) — `N` in a `FixedBuf<const N: Int>` body IS an
            # Int, with a different one per instantiation. It shadows nothing
            # and is never assignable, so it is resolved before the static
            # lookup and never enters a scope.
            const_type = self._const_param_types().get(expr.name)
            if const_type is not None:
                expr.const_param_name = expr.name
                return const_type
            # Module-level static (design 41): read like an immutable binding.
            static_sym = self.namespace.get_static(
                expr.name, self._accessor_vis_module())
            if static_sym is not None and self.namespace.is_accessible(expr.name):
                # DF-140f: resolution happens HERE, against this module's own
                # namespace, so this is the only place that knows WHICH
                # same-named private static was meant. Stamp its codegen symbol
                # — codegen works from one merged namespace and could not tell
                # two module-private `PT_LOAD`s apart on its own.
                if static_sym.mangled_name:
                    expr.resolved_static_symbol = static_sym.mangled_name
                # design 149: naming an `unsafe static var` is unsafe contact,
                # whatever its type. Recorded here rather than from the type,
                # because the unsafety is the declaration's, not the type's.
                if getattr(static_sym, 'is_var', False):
                    self._note_unsafe_static_contact(expr.name, expr)
                return static_sym.type
            # design 226, construction form 2: a NAMED FUNCTION written in a
            # `FuncPointer<F>`-expected position. Resolved after locals and
            # statics, never before — a binding that shares the name is what
            # the author wrote, on the ordinary precedence — and reached only
            # when the expectation is a function pointer, so no other program
            # sees a function name become a value (DF-172a stays open).
            fp_type = self._funcpointer_expectation(expr, None)
            if (fp_type is not None
                    and self.namespace.lookup_function_overloads(expr.name)):
                return self._check_funcpointer_named_function(expr, fp_type)
            # design 186 unit 7: a static initializer naming a static declared
            # BELOW it. "undefined variable" is technically true — nothing is
            # registered yet — and reads as a lie two lines above the
            # declaration. Static initializers fold in declaration order, so say
            # that instead.
            later = ((getattr(self, '_const_static_decls', None) or {})
                     .get((self._accessor_vis_module(), expr.name)))
            if later is not None:
                self._error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"static `{expr.name}` is declared after this point",
                    expr.line, expr.column,
                    hint="static initializers fold in DECLARATION ORDER, so one "
                         "may name only the statics above it — which is also "
                         "what makes a cycle impossible. Move the declaration up")
                return None
            # DF-247b: the EXPRESSION half of the unbound-qualifier refusal.
            # `data.Data()` under `import std.data.*` reads its head as a
            # variable, so it always ended here — with a true sentence and no
            # way to act on it. The hint is the type position's, from the same
            # helper, so both spellings of one mistake teach the same fix.
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined variable `{expr.name}`",
                expr.line, expr.column,
                hint=self._nonbinding_qualifier_hint(expr.name)
            )
            return None

        # Use-after-move: the binding was moved-from on some path reaching here.
        move_info = self._binding_move_info(var_info)
        if move_info is not None:
            _, move_line, _ = move_info
            if self._binding_move_is_provisional(var_info):
                # design 219 wave C, entry point 2. The earlier transfer was an
                # abstract-tier read; this second use proves it was a DUPLICATE
                # rather than a move, which is the requirement the call sites
                # discharge. Not an error here — at `T = Int` the same body is
                # perfectly legal.
                self._tier_req_second_use(var_info, expr.name, expr.line,
                                          move_line)
            else:
                self._error(
                    ErrorKind.USE_AFTER_MOVE,
                    f"use of moved variable `{expr.name}`",
                    expr.line, expr.column,
                    hint=f"value was moved at line {move_line} and can no longer be used"
                )
                return None

        # design 189: reading a root a task holds EXCLUSIVELY. A `[&var]`
        # capture excludes readers as well as writers — one writer XOR many
        # readers, over a window as long as the task. (A `[&x]` capture is a
        # reader itself and composes with this one silently.) A ref-captured
        # name inside the closure body resolves to the capture's own shadowing
        # binding, so a task reading what it borrowed never lands here.
        if self._task_borrows:
            borrow = self._task_borrow_for(var_info, writes=False)
            if borrow is not None:
                self._report_task_borrow(borrow, 'read', expr.line, expr.column,
                                         root=expr.name)

        # Auto-dereference reference types
        if var_info.type.kind == TypeKind.REFERENCE:
            return var_info.type.inner_type

        return var_info.type

    def _check_move_expr(self, expr: MoveExpr) -> Optional[SawType]:
        """Check a move expression.

        Records the source binding as moved-from (design 15). This runs for
        every `move x` regardless of the enclosing transfer site, so call
        arguments, struct-field inits, enum payloads, array/tuple elements and
        returns all mark the move uniformly. A double-move is caught here
        because the second `move` sees the binding already moved-from.
        """
        # Partial move (`move p.x`, `move p.x.y`, `move arr[i]`): forbidden on
        # every struct (design 35). Only whole bindings are movable. Reject with
        # a diagnostic naming the field/element and its base.
        if expr.path is not None:
            # design 219 unit A2: design 35's refusal is keyed on the place's
            # ROOT. A place the language tracks occupancy for keeps it; a place
            # behind a raw pointer tracks nothing, so the `move` spelling is
            # what declares the transfer. The place machinery owns that
            # question — see `_place_move_out_type`.
            elem = self._place_move_out_type(expr)
            if elem is not None:
                return elem
            # design 260 §3 (Option A): `move self.<field>` inside a CONSUMING
            # body. The one licensed crossing of design 35's ban, and of the
            # no-move-out-of-a-ref ban beside it — the referent is the callee's
            # to end, so a partially-emptied receiver is never observable. Every
            # other position, a NON-consuming `&var self` method included, falls
            # through to the refusal below exactly as before.
            handled, consumed_field = self._consuming_field_move_ok(expr)
            if handled:
                return consumed_field
            # design 131: `move h.s!` is still a partial move — the payload sits
            # inside a field, and retiring it would leave `h` half-owned. The
            # field-safe consuming read is `h.s.take()`.
            # design 260 §2 names the escape each shape actually has: a FIELD
            # moves out with `take()` (which writes a valid state back), an
            # indexed PLACE with `swap_out` (design 35's own out). The generic
            # advice stays for everything else.
            piece = self._render_lvalue_path(expr.path)
            if isinstance(expr.path, ArrayIndex):
                escape = (f"; an indexed place moves out with "
                          f"`swap_out` instead")
            elif isinstance(expr.path, MemberAccess):
                escape = (f"; a field moves out with `{piece}.take()`, which "
                          f"leaves a valid value behind")
            else:
                escape = ""
            hint = ("move the whole value (`move " + expr.variable + "`) or "
                    "restructure so the piece is its own binding" + escape)
            if expr.unwrap:
                hint = (f"`move` at an optional projection retires the whole "
                        f"BINDING, which a field cannot do; use "
                        f"`{self._render_lvalue_path(expr.path)}.take()` to move "
                        f"the payload out and leave `None` behind")
            self._error(
                ErrorKind.CANNOT_COPY,
                self._partial_move_message(expr.path),
                expr.line, expr.column,
                hint=hint
            )
            return None

        var_info = self.current_scope.lookup(expr.variable)
        if not var_info:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined variable `{expr.variable}`",
                expr.line, expr.column
            )
            return None

        # Use-after-move / double-move: the binding was already moved-from.
        move_info = self._binding_move_info(var_info)
        if move_info is not None:
            _, move_line, _ = move_info
            if self._binding_move_is_provisional(var_info):
                # design 219 wave C, entry point 3: the same reading as an
                # ordinary second use — the earlier abstract-tier transfer
                # duplicated rather than moved, and this `move` is the proof.
                self._tier_req_second_use(var_info, expr.variable, expr.line,
                                          move_line)
            else:
                self._error(
                    ErrorKind.USE_AFTER_MOVE,
                    f"use of moved variable `{expr.variable}`",
                    expr.line, expr.column,
                    hint=f"value was already moved at line {move_line} and can no longer be used"
                )
                return None

        # Disallow moving out of references - this would leave the referent invalid
        if var_info.type.kind == TypeKind.REFERENCE:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot move out of reference `{expr.variable}`",
                expr.line, expr.column,
                hint="references cannot have their contents moved out"
            )
            return None

        # design 188 unit 4: a `NoMove` value moves exactly ONCE, from its
        # constructor into its binding, and never again. Every other transfer
        # position is funnelled through `move` by the NoCopy machinery, so
        # refusing the funnel refuses them all — and this is the one place the
        # funnel passes through.
        if self._is_no_move_type(var_info.type):
            self._error(
                ErrorKind.CANNOT_COPY,
                f"cannot `move` `{expr.variable}`: `{var_info.type}` is "
                f"`NoMove`, so it lives where its constructor built it and may "
                f"not be relocated." + self._no_move_scope_note(var_info.type),
                expr.line, expr.column,
                hint=f"pass `&var {expr.variable}` to lend it, or build the "
                     f"value where it has to live. Replacing a referent whole "
                     f"through a `&var` stays legal — that destroys and "
                     f"constructs at one address rather than moving"
            )
            return None

        # design 189: the move-while-borrowed refusal, now that the borrow is
        # VISIBLE. This is probe 5, the confirmed silent use-after-free: main
        # never suspends before the move, so the moved-to value drops the
        # buffer, and the join then drives a task that reads the dead slot.
        if self._task_borrows:
            borrow = self._task_borrow_for(var_info, writes=True)
            if borrow is not None:
                self._report_task_borrow(borrow, 'move', expr.line, expr.column,
                                         root=expr.variable)

        # Record the move against the binding's identity.
        self._mark_binding_moved(var_info, expr.variable, expr.line, expr.column)

        # design 131: `move o!` transfers the binding and yields the PAYLOAD.
        # The binding is retired whole — no husk, no writeback — so the only
        # extra work here is unwrapping the result type.
        if expr.unwrap:
            if var_info.type.kind != TypeKind.OPTIONAL:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot force unwrap non-optional type `{var_info.type}`",
                    expr.line, expr.column,
                    hint=f"`move {expr.variable}!` is the payload-yielding move; "
                         f"`{expr.variable}` is not an optional, so write "
                         f"`move {expr.variable}`"
                )
                return var_info.type
            return var_info.type.inner_type

        return var_info.type

    def _partial_move_message(self, path: Expression) -> str:
        """Diagnostic for a forbidden partial move, naming the piece and base."""
        if isinstance(path, MemberAccess):
            base = self._render_lvalue_path(path.object)
            return f"cannot move out of field `{path.member}` of `{base}`"
        if isinstance(path, TupleIndex):
            base = self._render_lvalue_path(path.tuple_expr)
            return f"cannot move out of tuple element `{path.index}` of `{base}`"
        if isinstance(path, ArrayIndex):
            base = self._render_lvalue_path(path.array_expr)
            idx = self._render_index(path.index)
            return f"cannot move out of element `[{idx}]` of `{base}`"
        return f"cannot move out of `{self._render_lvalue_path(path)}`"

    def _check_reference_expr(self, expr: ReferenceExpr) -> Optional[SawType]:
        """Check a reference expression: &expr or &var expr.

        References can only be taken to lvalues (variables, fields, array elements).
        For mutable references (&var), the target must be mutable.
        """
        inner_type = self._check_expression(expr.expr)
        if inner_type is None:
            return None

        # A reference is only meaningful as a call argument (design 34, DF-163d):
        # references cannot be stored, returned, or bound to a variable. The
        # parser marks argument-position references (the place transform marks
        # the `&var` it builds out of a `lend`, which is the implicit lend a
        # `borrows` accessor makes); a reference anywhere else is rejected here.
        #
        # The one other blessed position is the operand of a cast to
        # `UnsafePointer<T>`/`UnsafeConstPointer<T>` (DF-163f) — the only
        # address-of the language has, and a crossing into the unsafe tier
        # rather than an escape: what survives the expression is a pointer, and
        # design 130's signature effect fences it from there.
        if not expr.in_argument_position and not expr.to_pointer_cast:
            sigil = "&var" if expr.mutable else "&"
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{sigil}` here is not a call argument, and references in Saw "
                f"are PARAMETERS ONLY — a reference borrows storage for the "
                f"duration of one call and may not escape it (designs 88/106; "
                f"the Law of Exclusivity is statically sound only because every "
                f"live reference belongs to a call still on the stack)",
                expr.line, expr.column,
                hint=f"a reference cannot be stored or bound: pass it straight "
                     f"to a `{sigil}` parameter, or — to hand out storage a "
                     f"value already owns — declare a `borrows` accessor "
                     f"(`... borrows -> T` with `lend`, design 141), which "
                     f"lends the place for a window rather than letting a "
                     f"pointer out"
            )
            # Recover as the reference type the author wrote, so one misplaced
            # `&` yields one message instead of dragging an "undefined variable"
            # cascade behind it.
            return SawType(TypeKind.REFERENCE, inner_type=inner_type,
                           reference_mutable=expr.mutable)

        # References can only be taken to lvalues
        if not self._is_lvalue(expr.expr):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "can only take reference to a variable, field, or array element",
                expr.line, expr.column,
                hint="references require an addressable location"
            )
            return None

        # For &var, check that the target is mutable
        if expr.mutable:
            if isinstance(expr.expr, Identifier):
                var_info = self.current_scope.lookup(expr.expr.name)
                # An immutable static rejects `&var STATIC` (design 41; an
                # `&STATIC` shared lend is fine). Statics are not in scope, so a
                # None var_info that names a static is the signal. An
                # `unsafe static var` (design 149) lends `&var` like any mutable
                # binding — naming it already made this function `unsafe`.
                static_sym = (self.namespace.get_static(
                    expr.expr.name, self._accessor_vis_module())
                    if var_info is None else None)
                if static_sym is not None and not getattr(static_sym, 'is_var', False):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot take mutable reference `&var` to static `{expr.expr.name}`: "
                        f"statics are immutable",
                        expr.line, expr.column,
                        hint="pass `&{0}` for a shared read, use an interior-"
                             "synchronized type (`Atomic<Int>`, `SpinLock<T>`), or "
                             "declare it `unsafe static var`".format(expr.expr.name)
                    )
                    return None
                # A `&var T` reference parameter is already a mutable borrow, so
                # re-borrowing it (`&var ref` — forwarding it to another `&var`
                # parameter, e.g. nested `Printable.format(into:)`, design 56) is
                # sound even though the binding itself is not a `var`.
                is_mut_ref_binding = (var_info is not None
                                      and var_info.type is not None
                                      and var_info.type.kind == TypeKind.REFERENCE
                                      and var_info.type.reference_mutable)
                # An IMMUTABLE reference binding (`r: &T`) is a shared borrow;
                # forwarding it as `&var` would silently UPGRADE it (design 106
                # forbids this — `&var` forwarding requires an incoming `&var`).
                # Give a forwarding-specific diagnostic rather than the generic
                # "declare with var" (the referent is not the caller's to re-var).
                is_imm_ref_binding = (var_info is not None
                                      and var_info.type is not None
                                      and var_info.type.kind == TypeKind.REFERENCE
                                      and not var_info.type.reference_mutable)
                if is_imm_ref_binding:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot forward `&` reference `{expr.expr.name}` as `&var`: "
                        f"a shared `&` reference cannot be upgraded to `&var`",
                        expr.line, expr.column,
                        hint="take the parameter as `&var T` to forward it mutably, "
                             f"or forward it as `&{expr.expr.name}`"
                    )
                    return None
                # The `&var` the place transform builds out of a `lend` is
                # exempt (design 146, DF-146d). `lend` names a PLACE, and the
                # transform has already proved this one is storage — the new
                # case being a match-arm binding, which the checker registers
                # immutable because a match ordinarily binds a copy. Here the
                # arm is matching a place WHERE IT SITS, so the binding names
                # the enum's own payload and the window writes back through it.
                from_lend = getattr(expr, 'from_lend', False)
                if (var_info and not var_info.mutable and not is_mut_ref_binding
                        and not from_lend):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot take mutable reference to immutable variable `{expr.expr.name}`",
                        expr.line, expr.column,
                        hint="declare with `var` to make it mutable"
                    )
                    return None
            elif isinstance(expr.expr, SelfExpr):
                # In a `&var self` method the receiver is itself a mutable
                # reference binding, so re-borrowing the WHOLE self (`&var self` —
                # forwarding the receiver onward, design 106) is sound, mirroring
                # the `&var ref` param re-borrow above. `self`'s VariableInfo is
                # always registered `mutable=False` (self-mutability lives on the
                # method, not the binding), so consult the enclosing method's
                # `self_mutable`. A `&self` method's receiver is a shared borrow —
                # `&var self` is rejected.
                if not self._self_borrow_is_exclusive():
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "cannot take mutable reference to immutable `self`",
                        expr.line, expr.column,
                        hint=self._shared_self_hint()
                    )
                    return None
            elif self._projects_from_self(expr.expr):
                # A `&self` receiver arrives BY VALUE, so a `&var` projection out
                # of it addresses the callee's own copy: the write compiles, runs,
                # and is thrown away with the copy (DF-146b — live in the tree
                # from the first `&self` method until design 146 closed it).
                # Design 106 already refuses to upgrade a `&` PARAMETER to `&var`;
                # this is the same rule reaching the receiver it never covered.
                #
                # The one exception is the `&var` the place transform builds out
                # of a `lend`: a borrows accessor's receiver travels by pointer
                # exactly so its window can write through, and that reference is
                # marked `from_lend`.
                if (not self._self_borrow_is_exclusive()
                        and not getattr(expr, 'from_lend', False)):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "cannot take a mutable reference into a `&self` "
                        "receiver: `self` is borrowed SHARED here, so `&var "
                        "self....` would hand out a mutable reference to a copy "
                        "and the write would be lost",
                        expr.line, expr.column,
                        hint=self._shared_self_hint()
                    )
                    return None

        # Return reference type
        return SawType(TypeKind.REFERENCE, inner_type=inner_type, reference_mutable=expr.mutable)

    def _projects_from_self(self, expr: Expression) -> bool:
        """Is this lvalue a projection rooted at `self` — `self.a`, `self.a[i]`,
        `self.t.0`, `self.opt!` — rather than storage reached some other way?

        A projection through a local (`if let buf = self.buffer  &var buf[i]`)
        is NOT one: the local holds a pointer value, and the storage it addresses
        is the heap's, not the receiver's copy.
        """
        node = expr
        while node is not None:
            if isinstance(node, SelfExpr):
                return True
            if isinstance(node, MemberAccess):
                node = node.object
            elif isinstance(node, ArrayIndex):
                node = node.array_expr
            elif isinstance(node, TupleIndex):
                node = node.tuple_expr
            elif isinstance(node, ForceUnwrap):
                node = node.expr
            else:
                return False
        return False

    def _is_lvalue(self, expr: Expression) -> bool:
        """Check if an expression is an lvalue (can have its address taken)."""
        # The payload of a force-unwrapped optional lvalue is itself an lvalue: its
        # address is the optional's payload slot (`&(opt!)` -> a pointer into the
        # stored value, guarded by a None-check). This lets a borrowed method
        # receiver held in an opt-encoded coroutine frame field be addressed
        # (design 84 nested suspending method embedding), and is a natural general
        # extension for taking a reference into an optional's contents.
        if isinstance(expr, ForceUnwrap):
            return self._is_lvalue(expr.expr)
        # A PLACE is storage by definition (design 141): `v.first()` and
        # `v.get(i)!` name an element the container already holds, so `&var`
        # into one is exactly as addressable as `&var v[i]`. The use-site
        # lowering turns the whole call into a window that spans it. The
        # annotation is stamped by `_check_place_use`, which has already run on
        # this node — `_check_reference_expr` checks the operand first.
        if getattr(expr, 'place_struct', None) is not None:
            return True
        # A TUPLE INDEX is storage on the same terms a struct field is
        # (DF-151j): `&var t.0` lends the element slot, so a `&var` callee
        # mutates the tuple's own element rather than a spilled copy.
        return isinstance(
            expr, (Identifier, MemberAccess, ArrayIndex, SelfExpr, TupleIndex))

    def _stamp_int_cast(self, expr: CastExpr, src_type: SawType,
                        to_type: SawType) -> bool:
        """Decide an integer cast's runtime check, or reject a constant operand
        that could not survive it (design 170).

        `x as UInt8` is CHECKED: a value the target cannot represent — by range
        or by sign — panics rather than silently becoming a different number.
        Narrowing `as` was the last silent value-corrupting operation in a
        language where arithmetic overflow, bounds, shifts and allocation
        failure all trap, so it joins them.

        Three outcomes, and the cost is the point of separating them:

        * TOTAL pair -> nothing stamped. Widening emits exactly what it emitted
          before: every source value has a target representation, so a check
          could only ever be true.
        * FOLDABLE operand -> the answer is known now. In range, nothing is
          stamped and the cast is free; out of range, this is a COMPILE ERROR
          rather than a program that builds and then aborts on its first run.
          `const_eval` is the same evaluator `static_assert` and `[T; N]` use
          (its own out-of-range rule at `const_eval.py:167` set this policy),
          so a folded cast and its runtime twin can never disagree.
        * anything else -> `cast_check`, one compare-and-branch on the
          narrowing/sign-change edge. That is the overflow-check cost class,
          and the optimizer still deletes it wherever it can prove the range
          itself.

        `src_type` is the operand type AFTER design-63 alias resolution and
        after a raw-backed enum has been reduced to its backing, so this reads
        real numeric kinds. Returns True when an error was reported.
        """
        from const_eval import CAST_INT_KINDS, const_eval, ConstEvalError
        src = CAST_INT_KINDS.get(src_type.kind)
        dst = CAST_INT_KINDS.get(to_type.kind)
        if src is None or dst is None:
            return False
        width = self.platform_int_width
        src_bits = src[0] or width
        dst_bits = dst[0] or width
        src_signed, dst_signed = src[1], dst[1]

        # Total: strictly wider and no sign the target cannot express, or the
        # identity. Signed -> unsigned is never total (a negative has no
        # unsigned image at any width), and same-width sign changes are not
        # either (`-1 as UInt8`, `UInt64.max as Int64`).
        if dst_bits > src_bits and (dst_signed or not src_signed):
            return False
        if dst_bits == src_bits and dst_signed == src_signed:
            return False

        lo = -(1 << (dst_bits - 1)) if dst_signed else 0
        hi = ((1 << (dst_bits - 1)) - 1) if dst_signed else (1 << dst_bits) - 1
        try:
            value = const_eval(expr.expr, env=self._const_param_env(),
                               width=width)
        except ConstEvalError:
            value = None
        if isinstance(value, bool):
            value = None
        if isinstance(value, int):
            if lo <= value <= hi:
                return False
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{value}` is not representable as `{to_type}`, so this cast "
                f"would always panic",
                expr.line, expr.column,
                hint=f"`{to_type}` holds {lo} through {hi}; write "
                     f"`{to_type}.from(truncating: ...)` to keep the low bits, "
                     f"or `{to_type}.from(...)` to get `None` instead"
            )
            return True
        expr.cast_check = True
        return False

    def _check_int_from(self, expr) -> Optional[SawType]:
        """`T.from(x) -> T?` and `T.from(truncating: x) -> T` (design 170).

        The two siblings of the checked cast, completing the accessor triple the
        rest of the language already follows: `as` traps, `from` returns the
        `None`, `from(truncating:)` does the thing you asked for on purpose.

        `from(_)` is defined UNIFORMLY across every integer source, total pairs
        included — `Int.from(x: Int8)` is always `Some`. Uniformity beats
        cleverness here: a generic body may rely on the shape existing for
        whatever `T` it is instantiated at, and the always-true check folds to
        nothing, so the uniformity is free.

        `from(truncating:)` keeps the low bits — the value mod 2^n. The LABEL is
        the operation (design 55/93 make labels overload identity), which is why
        there is no boolean parameter and therefore no nonsense
        `truncate: false` corner to define. It is the cast-shaped sibling of the
        `&+`/`&-`/`&*` wrapping operators.

        Neither one const-errors on an out-of-range constant the way `as` does:
        answering out-of-range IS what these are for.
        """
        target_kind = self._INT_LIMIT_TYPE_KINDS[expr.object.name]
        to_type = SawType(target_kind)
        if len(expr.arguments) != 1:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{to_type}.from` takes exactly one argument, "
                f"got {len(expr.arguments)}",
                expr.line, expr.column,
                hint=f"`{to_type}.from(x)` yields `{to_type}?`; "
                     f"`{to_type}.from(truncating: x)` keeps the low bits"
            )
            return None
        arg = expr.arguments[0]
        label = getattr(arg, 'name', None)
        if label is not None and label != "truncating":
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{to_type}.from` has no argument labeled `{label}`",
                expr.line, expr.column,
                hint=f"write `{to_type}.from(x)` for the checked conversion "
                     f"(`{to_type}?`), or `{to_type}.from(truncating: x)` to "
                     f"keep the low bits"
            )
            return None
        # No expectation is pushed onto the argument: `UInt8.from(300)` must be
        # the `None` this exists to produce, not a range error at the literal.
        from_type = self._check_expression(arg.value)
        if from_type is None:
            return None
        # Design 63: an alias projects toward its underlying first, then the
        # integer rules apply — the same order `as` uses.
        if from_type.is_struct() and self.get_type_alias_info(from_type.struct_name):
            from_type = self._get_underlying_type(from_type)
        from const_eval import CAST_INT_KINDS
        src = CAST_INT_KINDS.get(from_type.kind)
        if src is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{to_type}.from` expects an integer, got `{from_type}`",
                expr.line, expr.column,
                hint="a raw-backed enum converts with `e as Backing` and back "
                     "with `E.from(raw:)`" if from_type.kind == TypeKind.ENUM
                     else None
            )
            return None
        truncating = label == "truncating"
        expr.int_from = (target_kind, truncating, src[1])
        if truncating:
            return to_type
        return SawType(TypeKind.OPTIONAL, inner_type=to_type)

    def _check_cast_expr(self, expr: CastExpr) -> Optional[SawType]:
        """Check a type cast expression: expr as Type"""
        # DF-163f: `(&x) as UnsafePointer<T>` is the sanctioned crossing into the
        # unsafe tier, and the only address-of Saw has — std and the runtime take
        # the address of a local, a static or `self` this way, and the chained
        # `(&self) as UnsafePointer<TaskGroup> as Int` is the token idiom. The
        # cast hands lifetime responsibility to that tier: the value produced is
        # a POINTER, so no reference survives the expression, and design 130's
        # signature effect is what fences it from there on. This is the node that
        # knows the parent, so it marks the operand before the reference rule
        # below sees it. Read off the type AS WRITTEN (an alias for a pointer
        # type is not blessed) so a bad target type is still reported once.
        if (isinstance(expr.expr, ReferenceExpr)
                and expr.target_type is not None
                and expr.target_type.kind == TypeKind.POINTER):
            expr.expr.to_pointer_cast = True
        from_type = self._check_expression(expr.expr)
        if from_type is None:
            return None
        to_type = self._resolve_type(expr.target_type)
        # Write the resolved type back onto the AST, the same step a `let`
        # annotation takes: codegen reads `target_type` straight off the node, so
        # a module-qualified target reached it as the dotted spelling and died
        # with `Undefined struct: dep.Point`. Unreachable until DF-194a's fix let
        # a qualified alias RHS type-check at all — before that the cast was
        # refused one error earlier, comparing `dep.Point` against `Point`.
        if to_type is not None:
            expr.target_type = to_type
        int_kinds = {
            TypeKind.INT, TypeKind.UINT,
            TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
            TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
        }
        # Distinct-type projection (design 63): a value of a distinct `type`
        # alias may be cast TOWARD its underlying type. This is the sanctioned
        # explicit projection (it replaces the never-implemented `.value`).
        # ONE-DIRECTIONAL: `42 as UserId` stays an error (the reverse never
        # matches here — a primitive `from_type` is not an alias). We walk the
        # operand's alias chain toward the underlying:
        #   - if `to_type` is an alias ON that chain (a partial projection like
        #     `b as A` where `type B = A`), the cast is legal, result = to_type;
        #   - otherwise resolve `from_type` to its underlying and fall through to
        #     the normal kind-based rules with that underlying (so `id as Int`
        #     and `id as Int8` are ordinary integer casts, while a sibling alias
        #     `UserId as OrderId` finds no matching rule and errors).
        if from_type.is_struct() and self.get_type_alias_info(from_type.struct_name):
            # Walk the UNRESOLVED immediate targets so intermediate aliases stay
            # visible (`aliased_type` collapses the whole chain to the underlying).
            # This yields the set of distinct aliases strictly BELOW `from_type`
            # on its definition chain — a target in that set is a legal partial
            # projection; a sibling alias (same underlying, not on the chain) is
            # not, and reverse casts never reach here.
            ancestor_alias_names = self._alias_ancestor_names(from_type)
            # Partial projection: target is a distinct alias on the chain.
            if (to_type.is_struct() and to_type.struct_name in ancestor_alias_names):
                return to_type
            # Full projection: continue the kind-match against the underlying.
            from_type = self._get_underlying_type(from_type)
        # Raw-backed enum -> its backing integer (design 145 unit B2). TOTAL in
        # this direction: the enum IS its tag, so every value has an answer.
        # Only a DECLARED backing makes an enum castable — an ordinary enum's
        # ordinals are the compiler's business and reordering its cases must
        # stay a free edit. The inverse is partial and spelled `E.from(raw:)`.
        if from_type.kind == TypeKind.ENUM and to_type.kind in int_kinds:
            enum_info = self.get_enum_info(from_type.enum_name)
            raw_type = getattr(enum_info, 'raw_type', None) if enum_info else None
            if raw_type is None:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"enum `{from_type.enum_name}` has no backing type, so it "
                    f"cannot be cast to `{to_type}`",
                    expr.line, expr.column,
                    hint=f"declare one (`enum {from_type.enum_name}: {to_type} "
                         f"{{ case A = 0, ... }}`) to pin the case values; "
                         f"without it the tag values are not part of the type"
                )
                return None
            # Design 170: the enum IS its tag, so the cast is total AT THE
            # BACKING WIDTH and stays exactly as free as it was. Narrowing
            # BELOW the backing (`enum E: UInt16` value `as UInt8`) is an
            # ordinary integer narrowing and takes the ordinary check.
            if self._stamp_int_cast(expr, raw_type, to_type):
                return None
            return to_type
        if from_type.kind in int_kinds and to_type.kind == TypeKind.ENUM:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot cast `{from_type}` to enum `{to_type.enum_name}`: not "
                f"every value names a case",
                expr.line, expr.column,
                hint=f"use `{to_type.enum_name}.from(raw: ...)`, which returns "
                     f"an optional — an unrecognized value is data, not a trap"
            )
            return None
        if from_type.kind in int_kinds and to_type.kind in int_kinds:
            # Design 170. `from_type` is already past the design-63 alias walk
            # above, so an alias projection resolves FIRST and then takes the
            # integer rules — composition unchanged.
            if self._stamp_int_cast(expr, from_type, to_type):
                return None
            return to_type
        if from_type.kind == TypeKind.POINTER and to_type.kind == TypeKind.POINTER:
            return to_type
        # Reference -> raw pointer (design 42, slab regions): a `&T` immutable lend
        # (notably `&STATIC_ARRAY`) reinterpreted as an `UnsafePointer<...>` to the
        # referent's storage. Both are addresses at the LLVM level; the cast is the
        # explicit, unsafe bridge that lets a static region feed a slab allocator.
        if from_type.kind == TypeKind.REFERENCE and to_type.kind == TypeKind.POINTER:
            return to_type
        # Pointer <-> Int address round-trip (design 42, slab free-list): a slab
        # threads freed-chunk ADDRESSES through an `Atomic<Int>`, so it must turn a
        # raw pointer into its integer address (`ptr as Int`) and back
        # (`addr as UnsafePointer<Int8>`). Standard unsafe ptrtoint/inttoptr.
        if from_type.kind == TypeKind.POINTER and to_type.kind in int_kinds:
            return to_type
        if from_type.kind in int_kinds and to_type.kind == TypeKind.POINTER:
            return to_type
        if from_type.kind == TypeKind.STRING and to_type.kind == TypeKind.POINTER:
            if to_type.inner_type and to_type.inner_type.kind == TypeKind.INT8:
                return to_type
        if from_type.kind == TypeKind.POINTER and to_type.kind == TypeKind.STRING:
            if from_type.inner_type and from_type.inner_type.kind == TypeKind.INT8:
                return to_type
        # Distinct-alias projection to a non-integer primitive / String / struct
        # underlying (design 63): after resolving the operand's alias above,
        # an identity-kind cast is a legal reinterpretation (same layout). Int
        # identity is already covered by the integer rule; this handles
        # `type Name = String; n as String` and struct-underlying aliases.
        if from_type.kind == to_type.kind and from_type.kind in (
                TypeKind.STRING, TypeKind.FLOAT, TypeKind.BOOL):
            return to_type
        if (from_type.kind == to_type.kind == TypeKind.STRUCT
                and from_type.struct_name == to_type.struct_name):
            return to_type
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"cannot cast `{from_type}` to `{to_type}`",
            expr.line, expr.column
        )
        return None

    def _flag_enum_backing(self, operand, t):
        """The BACKING integer a raw-backed enum CASE denotes here, or None.

        Design 185 unit 3, and the boundary is the whole rule: the result of a
        bit operator over enum cases is the BACKING INTEGER, never the enum. A
        combined flag value (`Perm.Read | Perm.Write` = 3) need not be a
        declared case, so typing it as the enum would break `from(raw:)` and
        exhaustiveness alike (design 145) — an enum is a closed set of tags, and
        a bit SET over those tags is the integer they are tags for. That is the
        line Swift draws with `OptionSet` and Rust with `bitflags`.

        Only a CASE qualifies, and only in a const position: the operand must
        carry the tag value design 145 stamps, which is a compile-time constant
        of a known number. An enum-typed value in running code carries nothing
        and stays refused (unit 4).
        """
        if t is None or t.kind != TypeKind.ENUM:
            return None
        if getattr(operand, 'enum_raw_value', None) is None:
            return None
        if not self._in_const_position():
            return None
        info = self.get_enum_info(t.enum_name, from_type=t)
        return getattr(info, 'raw_type', None) if info is not None else None

    def _enum_bit_op_hint(self, op: str, *types):
        """The `as` fixit for a bit operator applied to an enum (design 185 u4).

        Ratified: arithmetic on an enum VALUE is not silently allowed. The `as`
        names the enum -> bitset crossing exactly as design 145 made `e as UInt8`
        the explicit total projection, and it is what keeps "a raw-backed enum
        value is always a declared case" true.
        """
        for t in types:
            if t is None or t.kind != TypeKind.ENUM:
                continue
            info = self.get_enum_info(t.enum_name, from_type=t)
            raw = getattr(info, 'raw_type', None) if info is not None else None
            if raw is None:
                return (f"`{t}` has no raw backing, so its cases are not "
                        f"numbers — give it one (`enum {t}: UInt8`, design 145) "
                        f"and project each operand with `as`")
            if op == '~':
                projection = f"`~(e as {raw})`"
            elif op in ('<<', '>>'):
                projection = f"`(e as {raw}) {op} n`"
            else:
                projection = f"`(a as {raw}) {op} (b as {raw})`"
            return (f"an enum is a closed set of tags, not a bit set: write "
                    f"{projection}. The result is the backing integer, because "
                    f"a combined value need not be a declared case")
        return None

    def _check_binary_op(self, expr: BinaryOp) -> Optional[SawType]:
        """Check a binary operation.

        THE COMPARISON FUNNEL (obligation 1). The Equatable/Comparable gating
        below is the ONE chokepoint every `==` `!=` `<` `>` `<=` `>=` reaches,
        in every position an operator can be written — a plain expression, a
        match-arm guard, a value-branch arm, an argument, a `while` condition,
        a generic body. It answers exactly one question now: does the operand
        conform? Design 216's stopgap hung a second question here — "does this
        comparison transitively reach a hand-written body that could consume its
        operand" — because `Equatable.equals(&self, other: Self)` took the right
        operand by value while the lowering passed a borrow. Design 239 gave the
        requirements `other: &Self`, so no transfer exists at any tier and the
        question has no content: the stopgap, its transitive walk, and the
        generic-body requirement design 219 wave C recorded for it are all
        deleted rather than relaxed.

        Nothing else about the operator path changed. `_check_binary_op` still
        builds no call node and codegen's `_emit_equals`/`_emit_compare` still
        hand the callee two operands directly — the right one by reference now
        (`_comparison_operand_ptr`), which is what the signature says.
        """
        # DF-235a/b: the adoption funnel already folded this whole operation to a
        # constant and range-checked it against the fixed-width slot it is going
        # into, so it IS that type — asking the operands would answer platform
        # `Int` (which is what left compound assignment's RHS refused by design
        # 195's operand agreement, against a target the value fits perfectly
        # well). Codegen emits the folded constant, not the operation.
        #
        # The pair of stamps is read, not `resolved_type`: the place lowering
        # UNCHECKS the tree between the two front-half passes (`place_uses.py`),
        # so `resolved_type` is a per-pass conclusion and is gone by the second
        # one, while the funnel's own annotations survive. Re-deriving it here is
        # what makes the second pass agree with the first.
        folded_type = expr.expected_type
        if (expr.const_folded_value is not None
                and self._const_adoption_slot(folded_type)):
            expr.resolved_type = SawType(folded_type.kind)
            return expr.resolved_type

        left_type = self._check_expression(expr.left)
        right_type = self._check_expression(expr.right)
        if left_type is None or right_type is None:
            return None
        left_underlying = self._get_underlying_type(left_type)
        right_underlying = self._get_underlying_type(right_type)
        int_kinds = {
            TypeKind.INT, TypeKind.UINT,
            TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
            TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
        }
        if expr.op in ['+', '-', '*', '/']:
            if expr.op in ['+', '-'] and left_underlying.kind == TypeKind.POINTER:
                if right_underlying.kind in int_kinds:
                    # Element-stride pointer arithmetic. The result is a raw
                    # pointer, so the design-130 trigger rule marks the enclosing
                    # function at the `_check_expression` chokepoint.
                    return left_type
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"pointer arithmetic requires integer offset, got `{right_type}`",
                        expr.line, expr.column
                    )
                    return None
            elif left_underlying.kind in (int_kinds | {TypeKind.FLOAT}) and \
                 right_underlying.kind in (int_kinds | {TypeKind.FLOAT}):
                # design 195 rule 1, entry 1: the two arithmetic peers must agree.
                # This arm used to be two — an int/int one that returned the LEFT
                # type whatever the right was, and a numeric one that answered
                # `Float` for a mixed pair, promising a promotion the lowering
                # does not implement (DF-195d).
                if not self._check_operand_agreement(
                        expr.left, expr.right, left_type, right_type,
                        f"operator `{expr.op}`", expr.line, expr.column):
                    return None
                if left_underlying.kind == TypeKind.FLOAT:
                    return SawType(TypeKind.FLOAT)
                adopted = self._adopt_bare_literal_operand(expr, left_type, right_type)
                return adopted if adopted is not None else left_type
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` cannot be applied to `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op == '%':
            if left_underlying.kind in int_kinds and right_underlying.kind in int_kinds:
                # design 195 rule 1, entry 1 (the modulo half).
                if not self._check_operand_agreement(
                        expr.left, expr.right, left_type, right_type,
                        f"operator `{expr.op}`", expr.line, expr.column):
                    return None
                adopted = self._adopt_bare_literal_operand(expr, left_type, right_type)
                return adopted if adopted is not None else left_type
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `%` requires integer operands, got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op in ['&+', '&-', '&*']:
            # Wrapping arithmetic (design 31): integer operands only. Float (and
            # everything else, including pointers) is rejected -- wraparound is
            # only defined for two's-complement integers.
            if left_underlying.kind in int_kinds and right_underlying.kind in int_kinds:
                # design 195 rule 1, entry 2. `&+` states that overflow wraps; it
                # states nothing about width, and the wrap is defined modulo the
                # operand type's own 2^n, so two operand types are two wraps.
                if not self._check_operand_agreement(
                        expr.left, expr.right, left_type, right_type,
                        f"operator `{expr.op}`", expr.line, expr.column):
                    return None
                adopted = self._adopt_bare_literal_operand(expr, left_type, right_type)
                return adopted if adopted is not None else left_type
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"wrapping operator `{expr.op}` requires integer operands, "
                    f"got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op in ['&', '|', '^', '<<', '>>']:
            # Bitwise AND/OR/XOR and shifts (design 50): integer operands only
            # (Bool uses `&&`/`||`; Float and everything else is rejected). The
            # result takes the left operand's type — for `>>` that also fixes the
            # arithmetic-vs-logical choice (signed left → arithmetic shift).
            #
            # design 185 unit 3: in a CONST position a raw-backed enum's CASE
            # reads as its backing integer, so `Perm.Read | Perm.Write` is the
            # flag constant it looks like. Everywhere else — and for an
            # enum-typed VALUE anywhere — the operator is refused and the `as`
            # projection is the spelling (unit 4).
            backing = self._flag_enum_backing(expr.left, left_type)
            if backing is not None:
                left_type = left_underlying = backing
            backing = self._flag_enum_backing(expr.right, right_type)
            if backing is not None:
                right_type = right_underlying = backing
            if left_underlying.kind in int_kinds and right_underlying.kind in int_kinds:
                # design 195 rule 1, entry 3 — the bitwise trio ONLY. `&`, `|` and
                # `^` are two peers: the result is a mask over both operands, so
                # both describe the same bit positions and therefore the same
                # width. Until this the right operand was brought to the left's
                # width with a ZERO extension whatever its signedness, so a
                # negative narrow operand masked against the wrong word.
                #
                # The SHIFTS fall through with no check — design 195 matrix row 6,
                # the documented exemption: a shift's right operand is a COUNT
                # rather than a peer.
                if expr.op in ('&', '|', '^'):
                    if not self._check_operand_agreement(
                            expr.left, expr.right, left_type, right_type,
                            f"operator `{expr.op}`", expr.line, expr.column):
                        return None
                    adopted = self._adopt_bare_literal_operand(
                        expr, left_type, right_type)
                    if adopted is not None:
                        return adopted
                return left_type
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` requires integer operands, "
                    f"got `{left_type}` and `{right_type}`",
                    expr.line, expr.column,
                    hint=self._enum_bit_op_hint(expr.op, left_type, right_type)
                )
                return None
        elif expr.op in ['&&', '||']:
            if left_underlying.kind == TypeKind.BOOL and right_underlying.kind == TypeKind.BOOL:
                return SawType(TypeKind.BOOL)
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` requires Bool operands, got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op in ['==', '!=', '<', '>', '<=', '>=']:
            # design 205: an INTEGER pair skips this general pre-check entirely
            # and goes straight to design 195's operand agreement below. The two
            # are answering different questions — this one asks "is a value of
            # one type a value of the other", the agreement asks "are these two
            # peers the same type, with a bare literal free to adopt" — and only
            # the second is right for an operator. While the platform pair was
            # admitted here they never disagreed; once general assignability went
            # same-kind-only, the pre-check fired FIRST on a correct comparison
            # (`probe >= 10` on a `UInt`, whose literal adopts) with the worse of
            # the two messages and no way out named.
            # design 257 §2: in a CONST position a raw-backed enum's CASE reads
            # as its backing integer HERE too. The bitwise arm above has always
            # done this, so a COMBINATION was already an integer by the time a
            # comparison saw it (`static_assert((Perm.Read | Perm.Write) == 3)`)
            # while the lone case beside it was ``cannot compare `Perm` with
            # `Int` `` — DF-282b's asymmetry at the operand position the ruling
            # names. Same predicate, same fence: only a CASE, only in a const
            # position, and an enum-typed VALUE anywhere is refused as ever.
            backing = self._flag_enum_backing(expr.left, left_type)
            if backing is not None:
                left_type = left_underlying = backing
            backing = self._flag_enum_backing(expr.right, right_type)
            if backing is not None:
                right_type = right_underlying = backing
            both_int = (left_underlying.kind in self._AGREEMENT_INT_KINDS
                        and right_underlying.kind in self._AGREEMENT_INT_KINDS)
            if not both_int and not self._types_compatible(left_type, right_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot compare `{left_type}` with `{right_type}`",
                    expr.line, expr.column
                )
                return SawType(TypeKind.BOOL)
            # design 195 rule 1, entry 4. A comparison is a two-peer operation
            # exactly as arithmetic is, and it is the position where a silent mix
            # is hardest to see: the operator yields a `Bool` either way, so a
            # wrong reading of one operand shows up only as a branch taken on the
            # wrong side. `i < u` has no answer right for both — read signed, a
            # large `UInt` is negative; read unsigned, a negative `Int` is
            # enormous — and it used to pick the LEFT operand's reading for both.
            if not self._check_operand_agreement(
                    expr.left, expr.right, left_type, right_type,
                    f"operator `{expr.op}`", expr.line, expr.column):
                return SawType(TypeKind.BOOL)
            # design 77 item 9: a bare integer literal compared against a typed
            # operand adopts that operand's type — otherwise `fd < 200` for
            # `fd: Int8` silently compared against the wrapped value -56. Now the
            # same adoption every other operator takes, so it also reaches the
            # NEGATED spelling (`fd < -2`) and pins the comparison's signedness.
            self._adopt_bare_literal_operand(expr, left_type, right_type)
            # Equatable gating (design 32): `==`/`!=` require the operand type to
            # conform to Equatable. Primitives and String conform builtin;
            # trivial (POD) structs and payload-free enums auto-conform;
            # everything else opts in with `extension T: Equatable {}`. A
            # `T: Equatable` bound satisfies this inside a generic body.
            if expr.op in ['==', '!='] and not self._bound_satisfied(left_type, "Equatable"):
                type_params = getattr(self, 'current_type_params', {})
                if left_type.kind == TypeKind.STRUCT and left_type.struct_name in type_params:
                    hint = f"add an `Equatable` bound: `<{left_type.struct_name}: Equatable>`"
                elif left_type.kind == TypeKind.STRUCT:
                    hint = f"add `extension {left_type.struct_name}: Equatable {{}}`"
                elif left_type.kind == TypeKind.ENUM:
                    hint = f"add `extension {left_type.enum_name}: Equatable {{}}`"
                else:
                    hint = None
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot compare values of type `{left_type}` with `{expr.op}`: "
                    f"`{left_type}` does not conform to `Equatable`",
                    expr.line, expr.column,
                    hint=hint
                )
            # Comparable gating (design 48): `< <= > >=` desugar to `compare()`.
            # Integer types and Float are ordered directly (Float keeps IEEE/NaN
            # semantics); raw pointers keep their historical address ordering;
            # String and user types require Comparable (builtin for String, opt-in
            # `extension T: Comparable {}` for structs/enums). A `T: Comparable`
            # bound satisfies this inside a generic body.
            if expr.op in ['<', '>', '<=', '>=']:
                lu = self._get_underlying_type(left_type)
                numeric = int_kinds | {TypeKind.FLOAT}
                if lu.kind not in numeric and lu.kind != TypeKind.POINTER:
                    if not self._bound_satisfied(left_type, "Comparable"):
                        type_params = getattr(self, 'current_type_params', {})
                        if left_type.kind == TypeKind.STRUCT and left_type.struct_name in type_params:
                            hint = f"add a `Comparable` bound: `<{left_type.struct_name}: Comparable>`"
                        elif left_type.kind == TypeKind.STRUCT:
                            hint = f"add `extension {left_type.struct_name}: Comparable {{}}`"
                        elif left_type.kind == TypeKind.ENUM:
                            hint = f"add `extension {left_type.enum_name}: Comparable {{}}`"
                        else:
                            hint = None
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot order values of type `{left_type}` with "
                            f"`{expr.op}`: `{left_type}` does not conform to "
                            f"`Comparable`",
                            expr.line, expr.column,
                            hint=hint
                        )
            return SawType(TypeKind.BOOL)
        return None

    def _check_unary_op(self, expr: UnaryOp) -> Optional[SawType]:
        """Check a unary operation."""
        # DF-235a/b, the `BinaryOp` rule's twin: the adoption funnel folded this
        # whole expression (a `~mask`, or a negated constant expression) against
        # a fixed-width slot and range-checked it there, so it IS that type. See
        # `_check_binary_op` for why the two annotations are what is read.
        folded_type = expr.expected_type
        if (expr.const_folded_value is not None
                and self._const_adoption_slot(folded_type)):
            expr.resolved_type = SawType(folded_type.kind)
            return expr.resolved_type

        operand_type = self._check_expression(expr.operand)
        if operand_type is None:
            return None
        underlying = self._get_underlying_type(operand_type)
        if expr.op == '-':
            # Unary negation (design 77 item 8): signed integers (platform `Int`
            # + fixed-width `Int8`..`Int64`) and `Float`. Negating a fixed-width
            # signed int is checked-overflow at codegen exactly like `Int`
            # (`-Int8.min` panics). Unsigned negation is a type error (there is no
            # negative unsigned value).
            signed_kinds = {TypeKind.INT, TypeKind.INT8, TypeKind.INT16,
                            TypeKind.INT32, TypeKind.INT64}
            unsigned_kinds = {TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16,
                              TypeKind.UINT32, TypeKind.UINT64}
            if underlying.kind in signed_kinds or underlying.kind == TypeKind.FLOAT:
                # A negated fixed-width integer LITERAL folds to the negated
                # constant at codegen (design 77 item 8); range-check that folded
                # value here so `-128i8` (= Int8.min) is legal but `-200i8` is a
                # clean error rather than a silent codegen truncation.
                if (isinstance(expr.operand, IntLiteral)
                        and underlying.kind in self._FIXED_INT_RANGES):
                    lo, hi = self._FIXED_INT_RANGES[underlying.kind]
                    neg = -expr.operand.value
                    if not (lo <= neg <= hi):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"integer literal {neg} does not fit in "
                            f"`{operand_type}` (range {lo}..={hi})",
                            expr.line, expr.column)
                        return None
                return operand_type
            elif underlying.kind in unsigned_kinds:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `-` cannot be applied to unsigned `{operand_type}` "
                    f"(an unsigned integer has no negation)",
                    expr.line, expr.column
                )
                return None
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `-` cannot be applied to `{operand_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op == 'not':
            if underlying.kind == TypeKind.BOOL:
                return SawType(TypeKind.BOOL)
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `not` requires Bool operand, got `{operand_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op == '~':
            # Bitwise complement (design 50): integer-only. `not` is the Bool
            # logical negation; `~` flips all bits of an integer.
            int_kinds = {
                TypeKind.INT, TypeKind.UINT,
                TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
                TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
            }
            # design 185: the flag-enum reading and the `as` fixit, on the same
            # terms the binary bit operators take them.
            backing = self._flag_enum_backing(expr.operand, operand_type)
            if backing is not None:
                operand_type = underlying = backing
            if underlying.kind in int_kinds:
                return operand_type
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `~` requires an integer operand, got `{operand_type}`",
                    expr.line, expr.column,
                    hint=self._enum_bit_op_hint('~', operand_type)
                )
                return None
        return None

    def _restore_authored_callee(self, node, attr: str) -> None:
        """Put the AUTHORED callee name and type arguments back on `node`.

        Driving and spawning a generic REWRITE the call in place: the callee
        becomes the monomorphized symbol and the type arguments are cleared, so
        the coroutine transform sees an ordinary non-generic call. That rewrite
        is not idempotent, and the front half runs more than once over the same
        AST — the place lowering re-enters over the tree it just checked
        (design 146). A second pass would look up `settle$1$Int`, the name the
        FIRST pass wrote, and find no such method.

        So the authored form is recorded the first time and restored on every
        later pass, which then re-derives exactly the same symbol.
        """
        saved = node.authored_callee
        if saved is None:
            node.authored_callee = (getattr(node, attr),
                                    getattr(node, 'type_args', None))
        else:
            setattr(node, attr, saved[0])
            node.type_args = saved[1]

    def _restore_authored_call(self, node) -> None:
        """`_restore_authored_callee` for a call of either shape."""
        from ast_nodes import MethodCall as _MC
        self._restore_authored_callee(
            node, 'method_name' if isinstance(node, _MC) else 'name')

    def _drive_generic_method(self, inner, struct_name, mode, expr):
        """design 70 (A5): drive a generic (method-level type params) suspending
        method. Monomorphize the method to a concrete method keyed by the mangled
        symbol, register + splice it onto the receiver's extension, record it a
        driven-method root, and rewrite the call so the coroutine transform's
        Part-0c method driving sees an ordinary non-generic method."""
        self._restore_authored_callee(inner, 'method_name')
        resolved_args = [self._resolve_type(a) for a in inner.type_args]
        if not all(self._is_concrete_type(a) for a in resolved_args):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{expr.name}(...)` of a generic method requires concrete type "
                f"arguments", inner.line, inner.column)
            return
        from codegen.mangle import mangle_named
        mono_name = mangle_named(inner.method_name, resolved_args)
        if not self._effect_queue_method_mono(struct_name, inner.method_name,
                                              resolved_args, mono_name):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"driving generic method `{struct_name}.{inner.method_name}` is not "
                f"supported (its template could not be monomorphized for effect "
                f"inference)", inner.line, inner.column)
            return
        self._effect_record_driven_method(struct_name, mono_name, mode)
        inner.method_name = mono_name
        inner.type_args = None

    def _drive_generic_struct_method(self, inner, struct_name, recv_type, mode, expr):
        """design 74 (A5-rest, shape 2): drive a suspending method on a GENERIC
        struct for a concrete receiver (`__saw_drive(b.run())`, `b: Holder<Int>`).
        Monomorphize the method over the struct's type params (T->Int), queue the
        clone+re-check for effect harvest, record the concrete driven-method root,
        and rewrite the call so the coroutine transform's Part-0c method driving
        sees an ordinary non-generic method (keyed by a per-instantiation name)."""
        self._restore_authored_callee(inner, 'method_name')
        struct_sym = self.namespace.lookup_struct(struct_name)
        tps = struct_sym.type_params or []
        resolved_args = [self._resolve_type(a) for a in (recv_type.type_args or [])]
        if len(resolved_args) != len(tps) or not all(
                self._is_concrete_type(a) for a in resolved_args):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{expr.name}(...)` of a method on generic struct `{struct_name}` "
                f"requires a fully concrete receiver", inner.line, inner.column)
            return
        entry = self._pristine_generic_struct_methods.get(
            (struct_name, inner.method_name))
        if entry is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"driving suspending method `{struct_name}.{inner.method_name}` on a "
                f"generic struct is not supported (its template could not be found "
                f"for monomorphization; design 74 A5-rest)",
                inner.line, inner.column)
            return
        pristine, _ext = entry
        # design 104 item 3: a method that is BOTH struct-generic (`Dual<T>`) AND
        # method-generic (`mix<U>`). Resolve the method's OWN type args from the call
        # and key the frame by BOTH instantiations (design 95's resolved-signature
        # keying, extended with the method's type args) — so 2 struct × 2 method
        # instantiations produce 4 distinct frames.
        method_tps = getattr(pristine, 'type_params', None) or []
        method_args = []
        if method_tps:
            if not inner.type_args or len(inner.type_args) != len(method_tps):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"driving generic method `{struct_name}.{inner.method_name}` "
                    f"requires {len(method_tps)} concrete method type argument(s)",
                    inner.line, inner.column)
                return
            method_args = [self._resolve_type(a) for a in inner.type_args]
            if not all(self._is_concrete_type(a) for a in method_args):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{struct_name}.{inner.method_name}<...>` requires concrete "
                    f"method type arguments", inner.line, inner.column)
                return
        from codegen.mangle import mangle_named
        # Encode both the struct's and the method's type args, so each
        # (struct instantiation, method instantiation) pair gets a distinct frame.
        mono_name = mangle_named(inner.method_name, resolved_args + method_args)
        # Carry the concrete receiver type (`Holder<Int>`) so the frame's `__recv`
        # points at the monomorphized struct codegen produces for it.
        concrete_recv = SawType(TypeKind.STRUCT, struct_name=struct_name,
                                type_args=resolved_args)
        self._effect_queue_generic_struct_method_mono(
            struct_name, inner.method_name, resolved_args, method_args, mono_name,
            concrete_recv)
        self._effect_record_driven_method(struct_name, mono_name, mode)
        inner.method_name = mono_name
        inner.type_args = None

    def _check_spawn(self, expr: FunctionCall) -> Optional[SawType]:
        """Type-check the `Thread.spawn { ... }` intrinsic (design 21 item 5,
        renamed from the bare `spawn { ... }` by design 242).

        `Thread.spawn` takes exactly one no-parameter closure and returns
        `Thread<T>` — `VoidThread` when the body's value is `Void` (ruling 2:
        the visible-`Void` rule makes `Thread<Void>` unwritable, so the void
        handle is its own named type, exactly as `VoidTask` is on the
        cooperative side). The closure escapes (it runs on another thread that
        outlives the call), so it is lowered with a heap env (E1). Every
        captured value's type must be `Send`: the capture audit walks
        `closure.captures`, resolves each name's type in the enclosing scope, and
        rejects the first non-`Send` capture, naming the capture and its type.
        """
        if len(expr.arguments) != 1 or not isinstance(expr.arguments[0].value, ClosureExpr):
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                "`Thread.spawn` takes exactly one closure argument: "
                "`Thread.spawn { ... }`",
                expr.line, expr.column
            )
            return None
        closure = expr.arguments[0].value
        if closure.parameters or closure.shorthand_param_count:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                "`Thread.spawn`'s closure takes no parameters",
                closure.line, closure.column
            )
        # Check the body as an escaping closure (heap env, move-only-capture
        # rejection).
        ctype = self._check_closure(closure, expected_type=None,
                                    as_call_argument=True, force_escape=True)
        # design 242 rulings 8 + 9: and it is a `sync` context that PERMITS a
        # `blocking` extern. The fresh OS thread runs no executor, so a
        # suspension there has nothing to resume it — before this the body
        # compiled as ordinary sync code and a `yield_now()` inside it was a
        # silent no-op (unit 0's probe). Blocking the thread on FFI is the
        # headline reason to spawn one, so that one source stays legal.
        self._effect_mark_thread_spawn_body(closure)
        self._check_spawn_brace_captures(closure, "Thread.spawn")
        result_type = SawType(TypeKind.VOID)
        if ctype is not None and ctype.kind == TypeKind.FUNCTION:
            result_type = ctype.func_return_type or SawType(TypeKind.VOID)
        if self._reject_never_task_body(
                "this closure's body",
                "the task never completes and `join` on its handle could never "
                "return", result_type, closure.line, closure.column):
            return None
        # Send capture-audit: every captured value must be safe to transfer to
        # the task thread. Resolve each capture's type and reject the first that
        # is not Send, naming the capture and its type.
        # DF-219c: asked against the enclosing generic's DECLARED bounds. An
        # abstract `T` has no thread-safety of its own, so the structural walk
        # answers False for every one — which made `<T: Send>` buy nothing and
        # `Send`-bounded generic fan-out unwritable. A declared bound IS the
        # answer here (the caller's own type argument is checked against it at
        # the call, by `_check_type_param_bounds`), and an UNBOUNDED `T` still
        # refuses, so nothing is laundered.
        assume = self._bounds_assumption()
        for cap_name in closure.captures:
            cap_info = self.current_scope.lookup(cap_name)
            if cap_info is None:
                continue
            note = self.namespace.send_check(cap_info.type, "spawn capture",
                                             assume=assume)
            if note is not None:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot `Thread.spawn`: captured `{cap_name}` of type "
                    f"`{cap_info.type}` is not `Send`",
                    closure.line, closure.column,
                    hint="only Send values may cross to another task; share via "
                         "`Arc` (and `Mutex` for mutation)." + note
                )
                break
        # The RESULT crosses too, in the other direction: the task computes it
        # on its own thread and `join()` hands it back to this one. The captures
        # were audited from the start and the result never was — `Thread<T: Send>`
        # made the HANDLE non-Send for a non-Send `T`, which stops the handle
        # from crossing a second boundary but says nothing about the crossing
        # every task makes. `Thread.spawn { make_raw(&var n) }` returning a struct
        # with an `UnsafePointer` field compiled (design 193 unit 6).
        result_note = self.namespace.send_check(result_type, "spawn result")
        if result_note is not None and not self._names_type_param(result_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot `Thread.spawn`: the closure's result type "
                f"`{result_type}` is not `Send`, so it cannot travel back from "
                f"the spawned thread to `join()`",
                closure.line, closure.column,
                hint="return a Send value; share thread-unsafe state through "
                     "`Arc` (and `Mutex` for mutation) or a `Channel` instead of "
                     "handing it back." + result_note
            )
        expr.spawn_result_type = result_type
        # design 242 ruling 2: a `Void` body's handle is the distinct `VoidThread`
        # — `Thread<Void>` cannot be written as an annotation (the visible-`Void`
        # rule, designs 122/132), and joining one has no value to hand back.
        if result_type.kind == TypeKind.VOID:
            # design 242 ruling 5: the handle's fate is load-bearing, so the
            # obligation is minted HERE — at the FORM, which is what ruling 6
            # keeps `group.spawn` out of. See the funnel in `types.py`.
            self._mint_spawn_obligation(expr, "VoidThread", "Thread.spawn")
            return SawType(TypeKind.STRUCT, struct_name=VOID_THREAD_STRUCT_NAME)
        self._mint_spawn_obligation(expr, f"Thread<{result_type}>", "Thread.spawn")
        return SawType(TypeKind.STRUCT, struct_name=THREAD_STRUCT_NAME,
                       type_args=[result_type])

    def _check_spawn_brace_captures(self, closure, form: str) -> None:
        """A SPAWNED BRACE CAPTURES NOTHING IMPLICITLY (design 242 ruling 10).

        The capture list of a spawn brace IS its parameter list: each entry
        transfers at the spawn, by value, at its own copy tier, and `[move x]`
        is legal. So an enclosing binding the body names and the list does not
        is a value crossing a concurrency boundary with nothing at the crossing
        to say so — which is the one thing the reader of a spawn site most needs
        spelled out, and the reason this is a rule rather than a convenience.
        An ordinary closure is untouched: its captures are read at the same
        frame by the same thread, and there is no boundary.

        THE FUNNEL (obligation 1). The rule quantifies over "every spawn form
        that takes a brace", and every one of them asks here rather than
        re-deriving the set. Entry points, all of them:
          * `_check_spawn` — `Thread.spawn { ... }`.
        (`Task.spawn { }` and `group.spawn { }` are the two ruling 10 names
        beside it. Both are refused at the argument today — the cooperative
        engines take a direct call to a named function, because a closure body
        gets no coroutine frame and a cooperative task's whole point is that it
        can suspend — so neither has a brace to check YET. The sugar that gives
        them one lifts the body into a hidden named function and routes it
        through the call form; when it lands it registers here, and the list it
        checks is the same list, with borrow entries additionally legal at
        `group.spawn` per ruling 6.)

        `closure.captures` is the body-scan set `_analyze_closure_captures`
        computed, with listed-but-unseen names appended (`_check_closure`), so
        the implicit set is exactly what the scan found and the list does not
        name.
        """
        listed = {spec.name for spec in (getattr(closure, 'capture_specs', None) or [])}
        implicit = [name for name in (closure.captures or []) if name not in listed]
        if not implicit:
            return
        shown = ", ".join(f"`{n}`" for n in implicit)
        example = ", ".join(implicit)
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"a spawned brace captures nothing implicitly, and this body names "
            f"{shown}",
            closure.line, closure.column,
            hint=f"name what crosses in the capture list — "
                 f"`{form} {{ [{example}] in ... }}`. The list IS the body's "
                 f"parameter list: each entry transfers at the spawn, by value, "
                 f"at its own copy tier, and `[move x]` is how a move-only "
                 f"value goes. Everything that crosses a concurrency boundary "
                 f"is spelled at the crossing"
        )

    def _reject_never_task_body(self, subject: str, consequence: str, result_type,
                                line: int, column: int) -> bool:
        """A task body may not be `-> Never` (design 228 unit 5, the v1 ruling).

        A task is a computation something later WAITS for. A `-> Never` body
        never completes, so the handle it mints has a result cell for a value
        that cannot exist and `join` on it could not return — a hang the type
        system can see coming, and one the compiler was quietly building: the
        handle came out `Task<Never>`, mangled through the escape hatch
        as `$Unknown$NEVER` (`mangle.py` has no `NEVER` case, and reaching that
        hatch is documented as a compiler bug).

        Blessing the never-Done frame as an honest forever-server type is
        re-proposable and forecloses nothing — it owes a `NEVER` mangle case, a
        `Slot<Never>` zero-size story, and a ruling on what `join` means. v1
        refuses instead, because a forever-task already has a spelling that
        works: `-> Void` with a loop.

        THE FUNNEL (obligation 1). Every position that starts a task from a
        named body asks this, and these are all of them:
          - `_check_taskgroup_spawn` — `group.spawn(f(args))`.
          - `_check_spawn` — the design-21b `Thread.spawn { ... }` closure form.
          - the `__saw_drive` / `__saw_drive_steps` intrinsic arm of
            `_check_function_call`.

        Returns True when it refused.
        """
        if result_type is None or result_type.kind != TypeKind.NEVER:
            return False
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"a task body may not be `Never`: {subject} never returns, "
            f"so {consequence}",
            line, column,
            hint="a task is something to wait for, and a `Never` body gives it "
                 "a result that cannot exist. Write a forever-task as `-> Void` "
                 "with a loop — `func serve() { while { ... } }` — and end it by "
                 "cancelling the task or breaking the loop"
        )
        return True

    def _bounds_assumption(self):
        """The enclosing generic's DECLARED thread-safety bounds, as the
        `(send_names, sync_names)` pair `namespace._send_sync` consults
        (DF-219c).

        A generic body is checked ONCE, abstractly, so a boundary inside it
        cannot ask a `T` what it structurally is — the only truth available is
        what the signature declares, and a declared bound is exactly a promise
        the caller is separately made to keep. Returns None when nothing in
        scope declares either bound, which is every non-generic body and keeps
        those queries byte-identical.
        """
        send, sync = set(), set()
        for name, bounds in (getattr(self, 'current_type_params', {}) or {}).items():
            for bound in (bounds or ()):
                simple = bound.rsplit('.', 1)[-1]
                if simple == "Send":
                    send.add(name)
                elif simple == "Sync":
                    sync.add(name)
        if not send and not sync:
            return None
        return (send, sync)

    def _names_type_param(self, t: Optional[SawType]) -> bool:
        """Does `t` mention a type PARAMETER of the body being checked?

        Thread-safety is a property of the INSTANTIATION, and an opaque `T` has
        none of its own: `spawn { produce<T>() }` inside a generic body must not
        be refused on the strength of a name. The concrete instantiation is
        judged where it is made.
        """
        if t is None:
            return False
        if (t.kind == TypeKind.STRUCT
                and t.struct_name in getattr(self, 'current_type_params', {})):
            return True
        parts = [t.inner_type, t.array_element_type, t.func_return_type]
        parts.extend(t.type_args or [])
        parts.extend(t.element_types or [])
        parts.extend(t.param_types or [])
        return any(self._names_type_param(p) for p in parts if p is not None)

    # ======================================================================
    # Overload resolution (design 55)
    # ======================================================================

    def _overload_cand_offset(self, cand, is_method: bool) -> int:
        """Parameter offset for a candidate: methods skip the `self` slot unless
        the candidate is static/init; free functions never skip."""
        if is_method and not (cand.is_static or cand.is_init):
            return 1
        return 0

    def _format_arg_types(self, arg_types) -> str:
        return ", ".join("<closure>" if at is None else str(at) for at in arg_types)

    def _format_overload_candidate(self, name: str, cand, is_method: bool,
                                   with_origin: bool = False) -> str:
        offset = self._overload_cand_offset(cand, is_method)
        ps = cand.param_types[offset:]
        ns = cand.param_names[offset:] if cand.param_names else []
        prefix = "<T> " if cand.type_params else ""
        # Design 66: show the labeled form (`name(label: Type, ...)`) so an
        # ambiguity diagnostic tells the user which labels disambiguate.
        parts = []
        for i, p in enumerate(ps):
            nm = ns[i] if i < len(ns) else None
            parts.append(f"{nm}: {p}" if nm else f"{p}")
        # Design 249: when the tie is between MODULES, the signatures are the
        # same text and only the origin tells them apart — so name it.
        origin = ""
        if with_origin:
            mod = tuple(getattr(cand, 'def_module', ()) or ())
            origin = f" [{'.'.join(mod)}]" if mod else " [this module]"
        return f"{prefix}{name}(" + ", ".join(parts) + f"){origin}"

    @staticmethod
    def _candidates_span_modules(candidates) -> bool:
        """Design 249: whether these candidates come from more than one defining
        module, which is what makes an ambiguity hint owe their origins."""
        return len({tuple(getattr(c, 'def_module', ()) or ())
                    for c in candidates}) > 1

    def _resolve_overload(self, display_name, candidates, arg_types,
                          has_type_args, is_method, line, column, arguments,
                          expr=None, base_subst=None):
        """Select the unique matching overload for a call (design 55 + 66 + 105).

        `arg_types[i] is None` marks a closure argument, which is neutral for
        matching (the closure-arg rule: resolve on the non-closure arguments;
        if candidates still tie and differ only in closure-param types they stay
        tied and yield the ambiguity error below).

        Design 66 LABEL FILTER runs FIRST: a candidate is eliminated if the
        call's labels cannot bind under the binding rule (unknown label, backward
        binding, missing forward-skip, arity). Surviving candidates then face the
        design-55 exact-type matching + tie-breaks, in order:
          1. exact beats optional-wrap (fewest implicit `T -> T?` wraps wins);
          2. resolution precedes Result/Optional auto-wrap (raw argument types);
          3. concrete beats generic (a concrete overload that matches wins over
             any generic candidate — design 55's exact-match model is untouched).
        Design 105: when NO concrete (or explicit-type-arg generic) candidate
        matches, generic candidates are tried by PER-CANDIDATE inference (each in
        its own sandbox); exactly one solving-and-type-matching candidate is
        picked (its solved type args stamped onto `expr.type_args`), two or more
        raise a clean ambiguity error listing the solving candidates + their
        solved type args, and zero falls through to the no-match diagnostic.
        Returns `(chosen FunctionSymbol, binding_mapping)`; the mapping is the
        per-source-argument logical parameter index for the winner (used to align
        argument checks and stamp `arg_plan`). Returns `(None, None)` after a
        no-match or ambiguity diagnostic listing the candidates in LABELED form.
        """
        n = len(arg_types)
        matches = []  # (candidate, wrap_penalty, is_generic, mapping)
        infer_cands = []  # design 105: generic candidates to try by inference
        for cand in candidates:
            is_generic = bool(cand.type_params)
            if has_type_args and not is_generic:
                continue
            offset = self._overload_cand_offset(cand, is_method)
            cparams = cand.param_types[offset:]
            cnames = list(cand.param_names[offset:]) if cand.param_names else []
            defaults = cand.default_values[offset:] if cand.default_values else []
            # LABEL FILTER (design 66): the labels + arity must bind. This also
            # subsumes the old arity gate for positional calls.
            mapping, berr = self._compute_binding(cnames, defaults, arguments)
            if berr is not None:
                continue
            # A generic overload with no explicit type args is a design-105
            # inference candidate (deferred; tried only if no concrete match).
            if is_generic and not has_type_args:
                infer_cands.append((cand, mapping, offset))
                continue
            tp_names = {tp.name for tp in (cand.type_params or [])}
            ok = True
            penalty = 0
            for i in range(n):
                p = mapping[i]
                pt = cparams[p] if p < len(cparams) else None
                at = arg_types[i]
                is_gp = pt is not None and (
                    pt.kind == TypeKind.TYPE_PARAM
                    or (pt.kind == TypeKind.STRUCT and pt.struct_name in tp_names))
                if is_gp or at is None or pt is None:
                    continue  # generic slot / closure arg: neutral
                if not self._types_compatible(at, pt):
                    # design 205: an INTEGER argument is judged on the two rules
                    # the platform-pair permission used to answer for. A bare
                    # literal or const has no width yet, so it fits EVERY integer
                    # parameter and stays neutral — which is what keeps `h(Int)`
                    # beside `h(Int8)` called `h(5)` the design-55 ambiguity
                    # rather than a silent pick. A typed argument fits only where
                    # a lossless widening takes it, and pays the penalty so an
                    # exact overload still outranks the widening one.
                    if self._int_transfer_pair(at, pt):
                        argexpr = (arguments[i].value
                                   if i < len(arguments) else None)
                        if self._adopting_int_source(argexpr):
                            if (at.kind in self._PLATFORM_INT_KINDS
                                    and pt.kind in self._PLATFORM_INT_KINDS):
                                # Design 137, restated for a pair general
                                # assignability no longer relates: between
                                # platform `Int` and `UInt` the EXACT kind wins,
                                # so `take(7)` picks `take(Int)` over
                                # `take(UInt)`. Signedness is the one axis a bare
                                # literal is already committed on; its WIDTH
                                # stays flexible, which is what keeps `h(Int)`
                                # beside `h(Int8)` at `h(5)` the design-55
                                # ambiguity rather than a silent pick.
                                penalty += 1
                            continue
                        if self._int_transfer_widens(at, pt):
                            penalty += 1
                            continue
                        ok = False
                        break
                    # design 51 + DF-169a: a `&concrete` argument fits a
                    # `&any Trait` slot when the concrete conforms. Candidate
                    # selection has to know that, or an overload set holding an
                    # existential parameter matches nothing and the erasure the
                    # argument pass would have performed is never reached.
                    if not self._erasure_compatible(at, pt):
                        ok = False
                        break
                    # An exact concrete overload outranks the erasing one, the
                    # same way an exact type outranks an optional wrap.
                    penalty += 1
                    continue
                if pt.is_optional() and not at.is_optional():
                    penalty += 1  # exact-vs-optional-wrap discriminator
                elif (at.kind in self._PLATFORM_INT_KINDS
                        and pt.kind in self._PLATFORM_INT_KINDS
                        and at.kind != pt.kind):
                    # Design 137: between platform `Int` and platform `UInt`, the
                    # EXACT one wins. The two are mutually compatible (design 53,
                    # so an unsuffixed literal can initialize either), which left
                    # `f(Int)` and `f(UInt)` tied at EVERY call site — including
                    # `f(someInt)`, where one is an exact match — and reported
                    # "ambiguous call" instead of picking. The pair was
                    # unwritable; `StringBuilder.append` needs both, because the
                    # signed overload cannot represent the top half of `UInt`.
                    #
                    # Deliberately narrow. A bare literal's WIDTH stays flexible,
                    # so `h(Int)` vs `h(Int8)` called `h(5)` is still the design-55
                    # ambiguity error (`overload_call_ambiguous_error`): 5 really
                    # could be either, and signedness is the only axis on which
                    # the argument type is already committed.
                    penalty += 1
            if ok:
                matches.append((cand, penalty, is_generic, mapping))
        if not matches:
            # Design 105: no concrete/explicit match — try generic inference per
            # candidate (each fully sandboxed, so a candidate that fails to solve
            # leaves zero residue). Requires the call node to run the solver.
            if infer_cands and expr is not None:
                solved = []  # (candidate, mapping, solved_type_args)
                for cand, mapping, offset in infer_cands:
                    targs = self._try_infer_overload_candidate(
                        cand, expr, mapping, offset, base_subst or {}, arg_types)
                    if targs is not None:
                        solved.append((cand, mapping, targs))
                if len(solved) == 1:
                    cand, mapping, targs = solved[0]
                    expr.type_args = targs
                    # Mark as INFERRED so a re-check (spawn/drive/coro re-typecheck)
                    # re-runs inference instead of mistaking these for explicit
                    # call-site type args (which would mis-resolve the overload).
                    expr.type_args_inferred = True
                    return cand, mapping
                if len(solved) >= 2:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"ambiguous call to `{display_name}`: type-argument "
                        f"inference matches multiple generic overloads "
                        f"({self._format_arg_types(arg_types)})",
                        line, column,
                        hint="give explicit type arguments or labels to select "
                             "one; matching: " + "; ".join(
                                 self._format_overload_candidate(
                                     display_name, c, is_method,
                                     with_origin=self._candidates_span_modules(
                                         [s[0] for s in solved]))
                                 + " with "
                                 + self._format_solved_type_args(c, ta)
                                 for c, _m, ta in solved))
                    return None, None
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"no overload of `{display_name}` matches the argument types "
                f"({self._format_arg_types(arg_types)})",
                line, column,
                hint="candidates: " + "; ".join(
                    self._format_overload_candidate(display_name, c, is_method)
                    for c in candidates)
            )
            return None, None
        minpen = min(m[1] for m in matches)
        matches = [m for m in matches if m[1] == minpen]
        if any(not m[2] for m in matches):
            matches = [m for m in matches if not m[2]]  # concrete beats generic
        if len(matches) == 1:
            return matches[0][0], matches[0][3]
        # Same-type different-label overloads under a POSITIONAL call tie here;
        # the labeled forms in the hint tell the user how to disambiguate.
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"ambiguous call to `{display_name}`: multiple overloads match the "
            f"argument types ({self._format_arg_types(arg_types)})",
            line, column,
            hint="matching candidates: " + "; ".join(
                self._format_overload_candidate(
                    display_name, m[0], is_method,
                    with_origin=self._candidates_span_modules(
                        [m2[0] for m2 in matches]))
                for m in matches)
        )
        return None, None

    def _try_infer_overload_candidate(self, cand, expr, mapping, offset,
                                      base_subst, arg_types):
        """Design 105: try to solve one generic overload candidate's own type
        arguments by inference (silently). Returns the solved type-argument list
        (one per `cand.type_params`) if inference succeeds AND every known actual
        argument type-matches the substituted parameter, else None. Fully
        sandboxed by `_solve_call_type_args`, so a failed attempt leaves no
        residue (moves / mono queues / effect edges roll back)."""
        abstract_params = cand.param_types[offset:]
        full = self._solve_call_type_args(
            cand.type_params, abstract_params, expr,
            mapping if mapping is not None else None,
            base_subst, None, "", expr.line, expr.column, silent=True,
            known_arg_types=arg_types,
            default_values=(cand.default_values[offset:]
                            if cand.default_values else None))
        if full is None:
            return None
        # Type-match: each KNOWN actual argument must be compatible with its
        # solved parameter (a closure arg is None here — it drove the solve).
        for i, at in enumerate(arg_types):
            if at is None:
                continue
            p = mapping[i] if mapping is not None else i
            if p >= len(abstract_params):
                return None
            pt = abstract_params[p].substitute(full)
            if not self._arg_type_ok(None, at, pt):
                return None
        return [full[tp.name] for tp in cand.type_params]

    def _format_solved_type_args(self, cand, type_args) -> str:
        """Render a candidate's solved type arguments as `<T=Int, U=String>` for
        the design-105 overload-ambiguity diagnostic."""
        parts = [f"{tp.name}={ta}"
                 for tp, ta in zip(cand.type_params or [], type_args or [])]
        return "<" + ", ".join(parts) + ">"

    def _arg_type_ok(self, arg_value, arg_type, expected_type, allow_wrap=True):
        """THE argument-position type check, with the call-site auto-wrap for
        BOTH payload kinds. Returns True if a value of `arg_type` may be passed
        where `expected_type` is wanted, recording on `arg_value` (an AST node)
        the wrap that makes it compatible — so codegen constructs `Some(x)` or
        `Ok(x)` at the argument edge.

        ENTRY POINTS — every spelling of "a value arrives in a declared slot by
        being written next to it" (process rule 1). They all ask this one
        predicate, which is why extending the rule to `Result` (DF-218f) was a
        change here and nowhere else:
          * `_check_function_call` / `_check_module_function_call` /
            `_check_method_call`'s free-function arm — positional and labeled
            call arguments alike (the label binding runs first and hands this
            the mapped parameter);
          * `_check_method_call`'s method arm and the trait-method arm;
          * `visit_StructInit` and the module-qualified struct-init arm — a
            struct literal's field values;
          * `_check_enum_init` — an enum payload;
          * the collection-literal element check;
          * `statements._check_default_value` — a defaulted parameter's own
            default;
          * `places._check_window_args` — an argument passed through a place
            window;
          * overload resolution, with `arg_value=None`, which is why the marks
            are CLEARED at entry: a candidate that loses must leave none behind.

        Ordering: the wrap is decided AFTER overload resolution (design 55 rule
        1 already preferred an exact match over a wrapped one), and injected at
        the argument-passing edge — the design-30 return machinery is untouched.
        Only ONE level in either direction (`T -> T?`, never `T -> T??`).
        `allow_wrap` is False at a generic-instantiation boundary: a bare type
        parameter that substitutes to a wrapper does NOT auto-wrap.

        Design 205: every slot above is a TRANSFER, so the compatibility question
        is `_transfer_compatible`'s, not `_types_compatible`'s — an integer
        arrives here with a known source side, and a lossless widening through
        the platform pair is the one implicit conversion it may take. A narrowing
        or a same-width sign flip is refused, and each caller reports it with
        `_int_conversion_hint`.
        """
        # Clear any wrap decided by an earlier candidate before deciding again.
        # (`autowrap_to_optional` is a declared field since design 126 R1, so the
        # old `hasattr` guard here was always true -- it read as conditional but
        # never was.)
        if arg_value is not None:
            arg_value.autowrap_to_optional = None
            arg_value.autowrap_to_result = None
            arg_value.autowrap_result_err = False
        if arg_type is None or expected_type is None:
            return True
        if (expected_type.is_result() and not arg_type.is_result()
                and not self._transfer_compatible(arg_type, expected_type)):
            return self._arg_result_wrap_ok(arg_value, arg_type, expected_type,
                                            allow_wrap)
        # A bare `None` argument to an optional parameter: annotate the literal
        # with the concrete optional type so codegen can build the None value
        # (call-argument None was previously untyped — same fix struct-field
        # init already applies).
        if arg_type.is_none_literal():
            if expected_type.is_optional() and arg_value is not None:
                arg_value.resolved_type = expected_type
            return self._types_compatible(arg_type, expected_type)
        # Not the wrap case (expected is non-optional, or the argument is itself
        # already optional): defer to ordinary compatibility, no wrap.
        if not (expected_type.is_optional() and not arg_type.is_optional()):
            return self._transfer_compatible(arg_type, expected_type)
        # Here: `expected` is optional and `arg` is a bare (non-optional) value —
        # a candidate one-level `T -> T?` auto-wrap (DF3, design 57).
        inner = expected_type.inner_type
        if inner is None or inner.is_optional():
            return False  # would be a >1-level wrap (e.g. Int -> Int??): reject
        if arg_type.kind == TypeKind.NEVER:
            return True   # a diverging expression fits any home
        if not self._transfer_compatible(arg_type, inner):
            return False
        if not allow_wrap:
            return False  # no auto-wrap across a generic-instantiation boundary
        if arg_value is not None:
            arg_value.autowrap_to_optional = expected_type
        return True

    def _arg_result_wrap_ok(self, arg_value, arg_type, expected_type,
                            allow_wrap) -> bool:
        """The `Result` half of the argument-position auto-wrap (DF-218f).

        RULED (user, Aug 14): `Result` gains the argument position `Optional`
        already had. The asymmetry was unprincipled — a bare value wrapped on
        the way OUT of a function and not on the way IN to one, and since Saw
        spells no `Ok(x)` constructor the argument position had no working
        spelling at all. `func put(&var self, value: T)` at `T = Result<…>` is
        how design 218 met it, but the wart is the user's.

        Same shape as the return position (`statements._check_return`), because
        it is the same question: `T` goes to Ok, `E` goes to Err, a `T` that is
        ALSO an `E` is the design-30 ambiguity and is refused, and a
        `Result<T?, E>` fed a bare `T` takes the DF-140d double wrap — into the
        Optional first, then into the Result — which is why both marks can ride
        one node.

        NOT here, deliberately: the ERASING wrap (`Result<T, Box<any Error>>`
        fed a concrete error). It needs the allocator and the concrete type the
        `ErasedErrWrap` node carries, which is a node the argument edge has no
        way to hold today — the mark carries a type, not a construction. The
        return position keeps it; an argument still writes the erasure itself.
        """
        if arg_type.kind == TypeKind.NEVER:
            return True                 # a diverging expression fits any home
        ok_type = expected_type.unwrap_result_ok()
        err_type = expected_type.unwrap_result_err()
        if ok_type is None or err_type is None:
            return False
        # A bare `None` reaches Ok only through an optional Ok type, and it is
        # compatible with everything by the none-literal rule — so it is asked
        # about first, exactly as the return position asks (DF-140d).
        if arg_type.is_none_literal():
            if not ok_type.is_optional():
                return False
            if not allow_wrap:
                return False
            if arg_value is not None:
                self._annotate_none_in_expr(arg_value, ok_type)
                arg_value.autowrap_to_result = expected_type
            return True
        fits_ok = self._transfer_compatible(arg_type, ok_type)
        fits_err = self._transfer_compatible(arg_type, err_type)
        if fits_ok and fits_err:
            return False                # design 30: ambiguous, no silent pick
        if not (fits_ok or fits_err):
            return False
        if not allow_wrap:
            return False
        # The DF-140d shape: `Result<T?, E>` fed a bare `T` fits by the same
        # `T -> T?` rule that admits it anywhere else, so the payload is one
        # wrap short of what the Ok slot holds. `_prepare_ok_payload` supplies
        # it as an AST node at the return position; here the mark does.
        double = (fits_ok and ok_type.is_optional()
                  and not arg_type.is_optional())
        if arg_value is not None:
            if double:
                arg_value.autowrap_to_optional = ok_type
            arg_value.autowrap_to_result = expected_type
            arg_value.autowrap_result_err = bool(fits_err)
        return True

    def _df3_allow_wrap(self, declared_type, tp_names=None):
        """Whether call-site optional auto-wrap may fire for this parameter.

        Design 57's DF3 said no when the parameter's optional-ness came from
        SUBSTITUTING a type parameter — auto-wrap was to be explicit at generic
        boundaries. DF-146m retires that: `m.insert("y", 7)` on a
        `Map<String, Int?>` errored with ``expects `Int?` but got `Int` `` while
        the identical call on a type whose parameter was WRITTEN `Int?` wrapped
        fine, and a bare `None` typed at that very position either way. One
        parameter, two answers, decided by how the callee happened to spell its
        signature — which is not something a caller can see or should care
        about.

        The wrap is still exactly ONE level (`_arg_type_ok` refuses `Int` into
        an `Int??`), and inference is unaffected: it runs first and solves a
        parameter from the argument's own type, so this only ever applies where
        the instantiation is already fixed — by the receiver, by explicit type
        arguments, or by another argument.

        Kept as a named predicate rather than deleted at its six call sites: the
        question "may this parameter auto-wrap" is a real one, and a later rule
        that needs to answer it differently has a place to live.
        """
        return True

    def _has_explicit_type_args(self, expr) -> bool:
        """Design 105: whether the call carries EXPLICIT (user-written) type args.
        Type args stamped by inference are marked `type_args_inferred` so a
        re-check (spawn/drive/coro re-typecheck) re-infers rather than treating
        the inferred args as an explicit-generic overload selection."""
        return bool(getattr(expr, 'type_args', None)) and not getattr(
            expr, 'type_args_inferred', False)

    def _call_has_labels(self, expr) -> bool:
        """Whether the call carries at least one labeled argument (design 66).
        Positional-only calls take the byte-identical legacy path everywhere;
        the labeled binding machinery engages only when this is True."""
        return any(getattr(a, 'name', None) is not None for a in expr.arguments)

    def _compute_binding(self, param_names, default_values, arguments):
        """Design 66 argument binding, no diagnostics. `param_names`/
        `default_values` are LOGICAL (self already stripped for methods).

        Arguments bind LEFT TO RIGHT: a positional argument binds the next
        unbound parameter; a labeled argument binds the parameter it names,
        provided that parameter sits AT or AFTER the next unbound position and
        every parameter skipped forward over it carries a default. No backward
        binding, no reordering. Returns `(mapping, err)` where `mapping[i]` is
        the logical parameter index bound by source argument `i`, and `err` is
        None on success or `(kind, code, detail, arg_index)` describing the
        first binding failure (`arg_index` is None for a trailing missing
        parameter). Codes: 'too_many', 'unknown', 'duplicate', 'backward',
        'missing'."""
        n = len(param_names)
        dvals = default_values or []
        has_default = [(i < len(dvals) and dvals[i] is not None) for i in range(n)]
        next_pos = 0
        mapping = []
        bound = set()
        for ai, arg in enumerate(arguments):
            if getattr(arg, 'name', None) is None:
                if next_pos >= n:
                    return (None, ('too_many', 'too_many', None, ai))
                mapping.append(next_pos)
                bound.add(next_pos)
                next_pos += 1
            else:
                if arg.name not in param_names:
                    return (None, ('unknown', 'unknown', arg.name, ai))
                target = param_names.index(arg.name)
                if target in bound:
                    return (None, ('duplicate', 'duplicate', arg.name, ai))
                if target < next_pos:
                    return (None, ('backward', 'backward', arg.name, ai))
                for k in range(next_pos, target):
                    if not has_default[k]:
                        return (None, ('missing', 'missing', param_names[k], ai))
                mapping.append(target)
                bound.add(target)
                next_pos = target + 1
        for k in range(n):
            if k not in bound and not has_default[k]:
                return (None, ('missing', 'missing', param_names[k], None))
        return (mapping, None)

    def _bind_args(self, expr, param_names, default_values, display_name):
        """Design 66 binding with call-site diagnostics. Returns `mapping`
        (source-arg index -> logical parameter index) and stamps `expr.arg_plan`
        (a list over logical parameters: the source-arg index that binds each,
        or None for a default-filled parameter) for codegen. Returns None after
        reporting the binding error. Only called for calls that carry a label."""
        mapping, err = self._compute_binding(param_names, default_values, expr.arguments)
        if err is not None:
            _, code, detail, ai = err
            if ai is not None and ai < len(expr.arguments):
                node = expr.arguments[ai].value
                line, col = node.line, node.column
            else:
                line, col = expr.line, expr.column
            if code == 'too_many':
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`{display_name}` was given more arguments than it has parameters",
                    line, col)
            elif code == 'unknown':
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{display_name}` has no parameter named `{detail}`",
                    line, col)
            elif code == 'duplicate':
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"argument `{detail}` specified more than once",
                    line, col)
            elif code == 'backward':
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"labeled argument `{detail}` cannot bind backward; "
                    f"arguments bind left to right",
                    line, col,
                    hint="labels may skip forward only over parameters with defaults")
            else:  # missing
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"missing argument for parameter `{detail}`",
                    line, col)
            return None
        plan = [None] * len(param_names)
        for ai, p in enumerate(mapping):
            plan[p] = ai
        expr.arg_plan = plan
        return mapping

    def _stamp_overload_plan(self, expr, logical_param_names, mapping):
        """Design 66: for a LABELED overloaded call, stamp `expr.arg_plan` (a list
        over the winner's logical parameters: source-arg index or None for a
        default-filled slot) so codegen interleaves mid-skipped defaults. A
        positional overloaded call keeps `arg_plan` unset (legacy codegen path)."""
        if mapping is None or not self._call_has_labels(expr):
            return
        plan = [None] * len(logical_param_names)
        for ai, p in enumerate(mapping):
            if p < len(plan):
                plan[p] = ai
        expr.arg_plan = plan

    def _aligned_call_meta(self, expr, mapping, param_types, param_names):
        """Return (param_types, param_names) positionally aligned to the source
        arguments for the exclusivity check. With no labels (`mapping is None`)
        this is the identity — the legacy positional alignment. With labels the
        binding may reorder/skip, so each source argument's parameter type/name
        is looked up through `mapping`."""
        if mapping is None:
            return param_types, param_names
        pt = list(param_types) if param_types is not None else []
        pn = list(param_names) if param_names is not None else []
        aligned_types = [pt[p] if p < len(pt) else None for p in mapping]
        aligned_names = [pn[p] if p < len(pn) else None for p in mapping]
        return aligned_types, aligned_names

    def _overload_arg_types(self, expr):
        """Type-check the non-closure arguments once (recording moves/effects a
        single time) and return the list of argument types, with `None` in each
        closure slot (deferred until the expected type is known)."""
        arg_types = []
        for arg in expr.arguments:
            if isinstance(arg.value, ClosureExpr):
                arg_types.append(None)
            else:
                arg_types.append(self._check_expression(arg.value))
        return arg_types

    def _finish_overloaded_args(self, expr, param_types, arg_types, mapping=None):
        """Shared tail for a resolved overloaded call: check each argument
        against its resolved parameter type (closures inferred now) and run the
        value-transfer chokepoint exactly once per argument. `param_types` is the
        winner's LOGICAL parameter list; `mapping[i]` (design 66) is the logical
        parameter index bound by source argument `i` — identity when the call is
        positional."""
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] if mapping is not None else i
            expected = param_types[p] if p < len(param_types) else None
            if isinstance(arg.value, ClosureExpr):
                at = self._check_closure(arg.value, expected, as_call_argument=True)
            else:
                at = arg_types[i]
            if self._try_existential_arg_coercion(arg, at, expected):
                pass  # `&concrete -> &any Trait` erasure (or its error) handled
            elif (at is not None and expected is not None
                    and not self._arg_type_ok(arg.value, at, expected)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument {i + 1} expects `{expected}` but got `{at}`",
                    arg.value.line, arg.value.column,
                    hint=self._int_conversion_hint(at, expected)
                )
            # Design 87: a bare literal adopts the resolved param's fixed-width
            # type (+ range check). Overload args are checked before the winner
            # is known, so this coerces POST-HOC (restamps the leaf's type).
            self._apply_literal_expected_type(arg.value, expected)
            self._check_value_transfer(arg.value, expected, "call argument",
                                       arg.value.line, arg.value.column)

    # ---------------------------------------------------------------- design 93
    # Generic type-argument inference. `v.map({ $0.to_string() })` solves the
    # method's own `<U>` from the closure's inferred return type; a free function
    # `wrap(x)` solves `<T>` from the argument type. Explicit `<...>` is always
    # allowed and wins; a partial explicit prefix pins its leading params and the
    # rest are inferred. Inference NEVER guesses: an underdetermined or
    # conflicting parameter is a clean error naming the parameter and suggesting
    # explicit arguments. The solved arguments are stamped back onto the call node
    # (`expr.type_args`) so codegen + the coroutine transform monomorphize an
    # inferred call byte-identically to an explicit one.
    def _infer_tp_name(self, t, names):
        """If `t` is a bare reference to a type parameter in `names`, its name."""
        if t is None:
            return None
        if t.kind == TypeKind.TYPE_PARAM and t.type_param_name in names:
            return t.type_param_name
        if (t.kind == TypeKind.STRUCT and not t.type_args
                and t.struct_name in names):
            return t.struct_name
        return None

    def _infer_types_equal(self, a, b) -> bool:
        """Structural equality used to detect a conflicting inference for one
        parameter (two different concrete solutions)."""
        try:
            return (self._type_key(self._resolve_type(a))
                    == self._type_key(self._resolve_type(b)))
        except Exception:
            return self._type_key(a) == self._type_key(b)

    def _unify_infer(self, pattern, actual, names, out):
        """Structurally match abstract `pattern` (which may mention parameter
        `names`) against concrete `actual`, recording solutions in `out`
        (name -> SawType). A parameter bound twice to unequal types records a
        conflict under `out['__conflict__']`. Best-effort: an unconstrained
        position is simply skipped (never an error here)."""
        if pattern is None or actual is None:
            return
        nm = self._infer_tp_name(pattern, names)
        if nm is not None:
            if actual.is_none_literal():
                # A bare `None` has no type of its own, so it constrains nothing
                # (DF-146l site 3, DF-174f). Binding the parameter to the untyped
                # optional made two calls go wrong in two directions: `idn(None)`
                # "solved" `T` and then died in codegen with no payload type, and
                # `pick(None, some)` reported `T` as required to be both
                # `OPTIONAL` and `Int?` — never a conflict, since every optional
                # discharges a `None`. Recording nothing leaves a later argument
                # free to fix the parameter (design 105's fixpoint does the rest)
                # and leaves a genuinely underdetermined call to the clean
                # "cannot infer type argument" error below.
                return
            prev = out.get(nm)
            if prev is None:
                out[nm] = actual
            elif not self._infer_types_equal(prev, actual):
                out.setdefault('__conflict__', {})[nm] = (prev, actual)
            return
        pk = pattern.kind
        if pk == TypeKind.FUNCTION and actual.kind == TypeKind.FUNCTION:
            for pp, ap in zip(pattern.param_types or [], actual.param_types or []):
                self._unify_infer(pp, ap, names, out)
            self._unify_infer(pattern.func_return_type, actual.func_return_type,
                              names, out)
            return
        if pk == TypeKind.OPTIONAL:
            # A bare argument auto-wraps to the optional parameter (design 30), so
            # a non-optional actual constrains the payload directly (`f(5)` into
            # `f(x: T?)` solves `T = Int`). A `None` actual carries no type.
            if actual.kind == TypeKind.OPTIONAL:
                inner = actual.inner_type
            elif actual.is_none_literal():
                inner = None
            else:
                inner = actual
            self._unify_infer(pattern.inner_type, inner, names, out)
            return
        if pk in (TypeKind.REFERENCE, TypeKind.POINTER):
            inner = actual.inner_type if actual.kind == pk else None
            self._unify_infer(pattern.inner_type, inner, names, out)
            return
        if pk == TypeKind.ARRAY:
            inner = (actual.array_element_type
                     if actual.kind == TypeKind.ARRAY else None)
            self._unify_infer(pattern.array_element_type, inner, names, out)
            # design 148 — the one inference case for a const parameter: a
            # `[T; N]` PARAMETER binds `N` from the argument's length, so
            # `func sum(xs: [Int; N]) -> Int` is callable on a `[Int; 4]`
            # without writing `<4>`. Only a length that is exactly the bare
            # parameter name participates; arithmetic (`[T; N + 1]`) is not
            # solved backwards, which would need a real constraint solver
            # rather than the structural matcher this is.
            if (actual.kind == TypeKind.ARRAY
                    and actual.array_size is not None
                    and pattern.array_size is None):
                se = pattern.array_size_expr
                if isinstance(se, Identifier) and se.name in names:
                    bound = SawType(TypeKind.CONST_VALUE,
                                    const_value=actual.array_size)
                    prev = out.get(se.name)
                    if prev is None:
                        out[se.name] = bound
                    elif not self._infer_types_equal(prev, bound):
                        out.setdefault('__conflict__', {})[se.name] = (prev, bound)
            return
        if pk == TypeKind.TUPLE and actual.kind == TypeKind.TUPLE:
            for pe, ae in zip(pattern.element_types or [],
                              actual.element_types or []):
                self._unify_infer(pe, ae, names, out)
            return
        if pk in (TypeKind.STRUCT, TypeKind.ENUM) and pattern.type_args:
            a_args = actual.type_args or []
            for i, pa in enumerate(pattern.type_args):
                aa = a_args[i] if i < len(a_args) else None
                self._unify_infer(pa, aa, names, out)
            return

    def _infer_snapshot(self):
        """Capture the mutable typechecker state the inference pre-pass touches so
        its trial argument checks (which discover argument types) can be rolled
        back — the real argument-checking loop runs downstream. A throwaway
        suspend node (key=None) catches effect edges recorded at the enclosing
        node level; per-instantiation queues are truncated on restore."""
        snap = (dict(self.moved_bindings), self.current_scope,
                len(self._suspend_stack), len(self._poly_call_edges),
                len(self._pending_mono), len(self._pending_method_mono),
                len(self._pending_generic_struct_method_mono),
                set(self._mono_built))
        self._suspend_stack.append(_SandboxNode(key=None, edges=[], direct=[]))
        return snap

    def _infer_restore(self, snap):
        (moved, scope, stack_n, poly_n, pm_n, pmm_n, pgm_n, mono_built) = snap
        self.moved_bindings = moved
        self.current_scope = scope
        del self._suspend_stack[stack_n:]
        del self._poly_call_edges[poly_n:]
        del self._pending_mono[pm_n:]
        del self._pending_method_mono[pmm_n:]
        del self._pending_generic_struct_method_mono[pgm_n:]
        self._mono_built = mono_built

    def _infer_label_mapping(self, expr, logical_param_names, default_values):
        """Design 105: for a LABELED call, the source-arg -> logical-parameter
        binding (design 66) so inference pairs each argument with the parameter
        it actually names. Returns None (positional identity) when the call has
        no labels or the binding fails (the real binding check downstream emits
        the diagnostic)."""
        if not self._call_has_labels(expr):
            return None
        mapping, err = self._compute_binding(
            logical_param_names, default_values, expr.arguments)
        return None if err is not None else mapping

    def _solve_call_type_args(self, type_params, abstract_params, expr, mapping,
                              base_subst, provided_type_args, what, line, column,
                              silent=False, known_arg_types=None,
                              default_values=None):
        """Infer this call's own generic type arguments (design 93 + 105).

        `abstract_params` are the callee's LOGICAL parameter types (receiver
        excluded), which may mention both the enclosing struct's type params
        (already concrete in `base_subst`) and this call's own `type_params`.
        Returns a complete substitution map (base_subst ∪ solved own params) or
        `None` after emitting a diagnostic. Leading `provided_type_args` pin their
        parameters explicitly (a partial prefix is allowed; explicit wins).

        `known_arg_types`, when given (the overload path already type-checked the
        arguments once), supplies each non-closure argument's type so the solver
        does NOT re-check it — avoiding a double `move`/effect record on the real
        state (the sandbox rolls back only what it touches).

        Design 105: `mapping` (source-arg index -> logical parameter index, or
        None for positional identity) makes inference honor labeled/out-of-order
        calls — arguments are paired with parameters BY LABEL before unification.
        A LATER argument that pins a parameter an earlier one gates is solved by
        the FIXPOINT (repeat passes until no new solution; bounded by param
        count; closures still solved after non-closure args each pass). `silent`
        suppresses the failure diagnostics so an overload candidate can be tried
        without emitting an error when it does not solve."""
        own = list(type_params)
        own_names = {tp.name for tp in own}
        out: Dict[str, SawType] = {}
        for tp, ta in zip(own, provided_type_args or []):
            out[tp.name] = self._resolve_type(ta)
        remaining = own_names - set(out.keys())
        if not remaining:
            return {**base_subst, **out}

        snap = self._infer_snapshot()
        try:
            # Fixpoint over the argument list (design 105): each pass runs the
            # non-closure args then the closures; a parameter gated by an argument
            # to its RIGHT is picked up on the next pass once that argument's own
            # parameters are known. Bounded by the parameter count — every pass
            # that changes anything solves at least one new name.
            max_passes = max(1, len(own))
            for _ in range(max_passes):
                before = len(out)
                # Phase 1: non-closure arguments pin the parameters they mention.
                # Unify against `base_subst` only (NOT the growing `out`) so two
                # arguments binding one parameter to unequal types still record a
                # conflict rather than silently comparing concrete-vs-concrete.
                for i, arg in enumerate(expr.arguments):
                    if isinstance(arg.value, ClosureExpr):
                        continue
                    p = mapping[i] if mapping is not None else i
                    if p >= len(abstract_params):
                        continue
                    if known_arg_types is not None:
                        at = known_arg_types[i]
                    else:
                        at = self._check_expression(arg.value)
                    if at is not None:
                        self._unify_infer(abstract_params[p].substitute(base_subst),
                                          at, remaining, out)
                # Phase 2: closures. Their parameter types are now concrete (from
                # the struct and from already-solved params); the inferred RETURN
                # type solves any remaining parameter (`map<U>`'s `U`).
                for i, arg in enumerate(expr.arguments):
                    if not isinstance(arg.value, ClosureExpr):
                        continue
                    p = mapping[i] if mapping is not None else i
                    if p >= len(abstract_params):
                        continue
                    expected = abstract_params[p].substitute({**base_subst, **out})
                    ct = self._check_closure(arg.value, expected,
                                             as_call_argument=True)
                    if ct is not None:
                        self._unify_infer(abstract_params[p].substitute(base_subst),
                                          ct, remaining, out)
                if '__conflict__' in out or len(out) == before:
                    break
            # Design 108: a parameter with a DEFAULT VALUE that is OMITTED at this
            # call drives inference from the default's OWN type when the parameter
            # it types is otherwise undetermined — `f(1)` with `b: T = 0` infers
            # `T = Int`. Consulted only AFTER argument-driven solving (a supplied
            # argument always wins), and only for a still-unsolved name, so it is
            # the last resort before the underdetermined error. The trial check is
            # inside the inference snapshot, so the default's moves/effects roll
            # back (they already tainted the callee at its declaration).
            if default_values and '__conflict__' not in out and (own_names - set(out.keys())):
                bound = (set(mapping) if mapping is not None
                         else set(range(len(expr.arguments))))
                for p, dv in enumerate(default_values):
                    if dv is None or p in bound or p >= len(abstract_params):
                        continue
                    if not (own_names - set(out.keys())):
                        break
                    dt = self._check_expression(dv)
                    if dt is not None:
                        self._unify_infer(abstract_params[p].substitute(base_subst),
                                          dt, remaining, out)
        finally:
            self._infer_restore(snap)

        conflict = out.pop('__conflict__', None)
        if conflict:
            if silent:
                return None
            nm = sorted(conflict.keys())[0]
            a, b = conflict[nm]
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot infer type argument `{nm}` for {what}: it is required to "
                f"be both `{a}` and `{b}`",
                line, column,
                hint=f"give the type argument(s) explicitly")
            return None
        for tp in own:
            if tp.name in out:
                continue
            if tp.default is not None:
                out[tp.name] = self._resolve_type(tp.default)
            else:
                if silent:
                    return None
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot infer type argument `{tp.name}` for {what}",
                    line, column,
                    hint=f"give the type argument(s) explicitly, "
                         f"e.g. `{what.split('`')[1] if '`' in what else '...'}"
                         f"<{tp.name}=...>`")
                return None
        return {**base_subst, **out}

    def _check_generic_call_defaults(self, expr, func_info, instantiated_param_types,
                                     mapping):
        """Design 108: validate each OMITTED default-valued parameter of a generic
        call against its INSTANTIATED parameter type.

        The design-53 declaration-time check runs against the abstract type
        parameter and is a no-op for a generic function, so a
        `func f<T>(a: Int, b: T = 0)` never has its `0` checked against a concrete
        `T` until a call fixes `T`. This is that check, anchored at the CALL: it
        turns the former `list index out of range` codegen ICE (a call emitted
        with too few args, or a non-coercible literal materialized at the wrong
        LLVM type) into a clean, actionable diagnostic. A bare integer literal
        default follows Saw's literal rules — it adopts an integer instantiation
        (range-checked) and is rejected against a non-integer one (a bare `0` does
        not become a `Float`). Side-effect-free: the default's own moves/effects
        already tainted the callee at its declaration, so a non-literal default's
        trial check is sandboxed."""
        dvals = func_info.default_values or []
        if not any(dv is not None for dv in dvals):
            return
        bound = (set(mapping) if mapping is not None
                 else set(range(len(expr.arguments))))
        for p, dv in enumerate(dvals):
            if dv is None or p in bound or p >= len(instantiated_param_types):
                continue
            expected = instantiated_param_types[p]
            if expected is None:
                continue
            pname = (func_info.param_names[p]
                     if p < len(func_info.param_names) else f"#{p}")
            rt = self._resolve_type(expected)
            ut = self._get_underlying_type(rt) if rt is not None else None
            # Bare integer literal (the `b: T = 0` case): adopt an integer
            # instantiation with a range check; reject a non-integer one.
            if isinstance(dv, IntLiteral) and getattr(dv, 'suffix', None) is None:
                if ut is not None and ut.kind in self._FIXED_INT_RANGES:
                    lo, hi = self._FIXED_INT_RANGES[ut.kind]
                    if not (lo <= dv.value <= hi):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"default value {dv.value} for parameter `{pname}` does "
                            f"not fit `{expected}` (range {lo}..={hi})",
                            expr.line, expr.column,
                            hint="the default is checked against the instantiated "
                                 "type at this call")
                    continue
                if ut is not None and ut.kind in (TypeKind.INT, TypeKind.UINT):
                    continue
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"default value for parameter `{pname}` has type `Int` but the "
                    f"parameter is instantiated as `{expected}` at this call",
                    expr.line, expr.column,
                    hint="a bare integer literal does not adopt a non-integer type; "
                         "pass the argument explicitly here")
                continue
            # General default: sandbox the trial type check (no move/effect leak).
            snap = self._infer_snapshot()
            try:
                dt = self._check_expression(dv)
            finally:
                self._infer_restore(snap)
            if dt is not None and not self._arg_type_ok(None, dt, rt, allow_wrap=False):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"default value for parameter `{pname}` has type `{dt}` but the "
                    f"parameter is instantiated as `{expected}` at this call",
                    expr.line, expr.column,
                    hint="the default is checked against the instantiated type at "
                         "this call")

    def _check_type_param_bounds(self, type_params, type_map, line, column,
                                 callee_decl=None, display=None):
        """Verify each parameter's concrete binding in `type_map` satisfies the
        parameter's trait bounds, naming the concrete (possibly inferred) type in
        the failure. Mirrors the free-function bound checks; used by the generic
        METHOD path (both explicit and inferred), which previously did none.

        design 219 wave C: this is also discharge entry point 2 — passing
        `callee_decl` records the call's obligation to satisfy the callee's
        INFERRED tier requirement, which is resolved at finalize. It serves the
        overloaded free-function, module-qualified, instance-method and
        static-method paths; the singleton free-function path records its own
        (it does not route through here), as do generic-struct instantiation
        and a method call's RECEIVER type arguments.
        """
        if callee_decl is not None:
            self._tier_record_obligation(callee_decl, type_params, type_map,
                                         display or "this call", line, column)
            # design 219 wave C (DF-217k): the per-instance half of design
            # 130's signature rule rides the same sites — it needs exactly the
            # same (callee, type arguments) pair.
            if getattr(callee_decl, 'param_types', None) is not None:
                self._tier_check_instance_unsafe(
                    callee_decl, display or "this call", type_map, line, column)
        for tp in type_params:
            resolved_arg = type_map.get(tp.name)
            if resolved_arg is None:
                continue
            concrete_name = None
            if resolved_arg.kind == TypeKind.STRUCT:
                concrete_name = resolved_arg.struct_name
            elif resolved_arg.kind == TypeKind.ENUM:
                concrete_name = resolved_arg.enum_name
            in_scope_param = (resolved_arg.kind == TypeKind.STRUCT
                              and resolved_arg.struct_name
                              in getattr(self, 'current_type_params', {}))
            for bound in tp.bounds:
                if bound not in ("Send", "Sync") and self.get_trait_info(bound) is None:
                    self._error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"unknown trait `{bound}` in type parameter bound",
                        line, column,
                        hint=self._retired_trait_hint(bound))
                    continue
                # THE Copy family goes through `_bound_satisfied` like every
                # other bound (design 219). This site used to special-case
                # `Copy` with a predicate that ignores the in-scope type-param
                # bounds environment — the third of three entry points the
                # collapse found for one rule, and the reason obligation 1 asks
                # for a funnel.
                ok = self._bound_satisfied(resolved_arg, bound)
                if ok:
                    if concrete_name and not in_scope_param:
                        for an, at in self.namespace.get_type_assignments(
                                concrete_name, bound).items():
                            type_map[an] = at
                    continue
                if bound in self._SILENT_COPY_BOUND_NAMES:
                    hint = ("the `Copy` tier is what duplicates silently — a "
                            "trivially-copyable type, or one whose members the "
                            "compiler retains; a type that copies only with a "
                            "spelled `.copy()` needs an `ExplicitCopy` bound "
                            "here instead")
                elif bound == "ExplicitCopy":
                    hint = (f"add `@synthesize extension {concrete_name}: "
                            f"ExplicitCopy {{}}`" if concrete_name else
                            "the type must be duplicable: on the `Copy` tier, "
                            "or declaring `ExplicitCopy`")
                elif in_scope_param:
                    hint = (f"add the bound to the enclosing signature: "
                            f"`<{resolved_arg.struct_name}: {bound}>`")
                elif concrete_name:
                    hint = f"add `extension {concrete_name}: {bound} {{ ... }}`"
                else:
                    hint = None
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"type `{resolved_arg}` does not satisfy the `{bound}` bound",
                    line, column, hint=hint)

    def _receiver_type_subst(self, struct_info, type_args, method_info,
                             subst=None):
        """What this RECEIVER binds the callee's owning declaration's type
        parameters to.

        THE FUNNEL for that question, over all four call shapes (obligation 1).
        Entry points: `_check_method_call` and `_check_overloaded_method_call`
        (instance, receiver args off the object's type),
        `_check_static_method_call` and `_check_overloaded_static_method_call`
        (static, receiver args off the type spelling, design-37 default-filled
        before they arrive here).

        Binds the TYPE's declared parameter names, and then — DF-216h — the
        OWNING EXTENSION's aliases for the same positions. An extension may
        rename what it re-declares (`extension Pair<U>` over `struct Pair<A>`),
        and the method's signature is written in the extension's names, so a
        map keyed only by the struct's left every such signature abstract:
        ``argument `other` expects `&Pair<U>` but got `&Pair<String>` ``. Both
        names denote the same position, so carrying both is a rename, not an
        ambiguity.

        `subst` is updated in place when given (the caller may already hold the
        struct-keyed half); the map is returned either way.
        """
        if subst is None:
            subst = {}
        args = list(type_args or [])
        declared = list(getattr(struct_info, 'type_params', None) or [])
        for tp, ta in zip(declared, args):
            subst[tp.name] = ta
        owner = list(getattr(method_info, 'owner_type_params', None) or [])
        for declared_name, alias in self.ext_param_aliases(owner, declared):
            bound = subst.get(declared_name)
            if bound is not None:
                subst[alias] = bound
        return subst

    def _fold_method_type_args(self, expr, method_info, type_subst,
                               self_offset: int) -> bool:
        """Bind the CALLEE's OWN generic type parameters at a method call site.

        THE FUNNEL for "what does this call bind the method's `<U>` to" on the
        singleton (non-overloaded) method paths. Explicit `<...>` wins; an
        omitted or partial list is INFERRED from the arguments (design 93 +
        105); the solution folds into `type_subst` — which arrives carrying the
        receiver's struct substitution — is bound-checked (design 219 wave C's
        discharge entry point 2 rides that check), and is stamped back onto
        `expr.type_args` so codegen and the coroutine transform monomorphize an
        inferred call byte-identically to an explicit one.

        Entry points: `_check_method_call` (instance receiver, `self_offset=1`
        — logical parameter 0 is `self`) and `_check_static_method_call` (no
        receiver, `self_offset=0`). DF-216c: the static path had no counterpart
        to this block at all, so a generic static's `U` reached the argument
        check unsubstituted on every spelling — inference and an explicit
        `<Int64>` alike. The OVERLOADED twins bind their type args inside
        `_resolve_overload` instead: there the question is which candidate wins,
        and the winner's arguments come back stamped on the node.

        Returns False when the solve failed — a diagnostic was emitted and the
        caller should abandon the call — and True otherwise.
        """
        method_type_params = method_info.type_params or []
        provided_type_args = expr.type_args or []
        if not method_type_params:
            if provided_type_args:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"method `{expr.method_name}` is not generic but was called "
                    f"with type arguments",
                    expr.line, expr.column
                )
            return True
        if len(provided_type_args) > len(method_type_params):
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"method `{expr.method_name}` expects {len(method_type_params)} "
                f"type argument(s), got {len(provided_type_args)}",
                expr.line, expr.column
            )
            return True
        if len(provided_type_args) < len(method_type_params):
            off = self_offset
            defaults = (method_info.default_values[off:]
                        if method_info.default_values else None)
            # Design 105: label-map before unification (logical param names
            # exclude the receiver `self`).
            infer_mapping = self._infer_label_mapping(
                expr, method_info.param_names[off:], defaults)
            full = self._solve_call_type_args(
                method_type_params, method_info.param_types[off:], expr,
                infer_mapping, type_subst, provided_type_args,
                f"method `{expr.method_name}`", expr.line, expr.column,
                default_values=defaults)
            if full is None:
                return False
            expr.type_args = [full[tp.name] for tp in method_type_params]
            for tp in method_type_params:
                type_subst[tp.name] = full[tp.name]
        else:
            for tp, ta in zip(method_type_params, provided_type_args):
                type_subst[tp.name] = self._resolve_type(ta)
        self._check_type_param_bounds(
            method_type_params, type_subst, expr.line, expr.column,
            callee_decl=method_info.ast_node,
            display=f"`{expr.method_name}`")
        return True

    def _check_overloaded_function_call(self, expr, candidates):
        """Resolve and check a call to an overloaded free function (design 55).
        Design 105: a generic overload may be selected by type-argument
        inference when no concrete candidate matches."""
        arg_types = self._overload_arg_types(expr)
        func_info, mapping = self._resolve_overload(
            expr.name, candidates, arg_types, self._has_explicit_type_args(expr),
            is_method=False, line=expr.line, column=expr.column,
            arguments=expr.arguments, expr=expr, base_subst={})
        if func_info is None:
            return None
        # Concrete overload: stamp its codegen symbol so codegen calls the right
        # definition. A generic overload keeps type-argument instantiation naming
        # (routed through the normal generic path), so it is left unstamped.
        if func_info.mangled_name:
            expr.resolved_symbol = func_info.mangled_name
        self._stamp_overload_plan(expr, func_info.param_names, mapping)
        # Single chokepoint: the effect edge is recorded to the RESOLVED callee.
        self._effect_call_function(func_info, expr.name, expr.line)
        if func_info.type_params:
            type_map = {}
            for tp, ta in zip(func_info.type_params, expr.type_args or []):
                type_map[tp.name] = self._resolve_type(ta)
            # Design 105: inferred (or explicit) type args are bound-checked.
            self._check_type_param_bounds(
                func_info.type_params, type_map, expr.line, expr.column,
                callee_decl=func_info.ast_node, display=f"`{expr.name}`")
            # design 70 (A5): record the deferred poly-call edge so a suspending
            # instantiation taints the caller / drives (mirrors the singleton
            # generic path), only when the args are fully concrete.
            resolved_args = [type_map.get(tp.name) for tp in func_info.type_params]
            if all(a is not None and self._is_concrete_type(a)
                   for a in resolved_args):
                self._effect_record_poly_call(
                    expr.name, resolved_args, f"`{expr.name}`", expr.line)
            param_types = [t.substitute(type_map) for t in func_info.param_types]
            return_type = (func_info.return_type.substitute(type_map)
                           if func_info.return_type else func_info.return_type)
            # Design 108: an omitted default on the winning generic overload is
            # checked against its instantiated type here too (mirrors the singleton
            # generic path), so `g<Float>(1)` selecting a `b: T = 0` overload is a
            # clean error rather than a codegen ICE.
            self._check_generic_call_defaults(expr, func_info, param_types, mapping)
        else:
            param_types = func_info.param_types
            return_type = func_info.return_type
        self._finish_overloaded_args(expr, param_types, arg_types, mapping)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping if self._call_has_labels(expr) else None,
            param_types, func_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments], aligned_types,
                                     param_names=aligned_names)
        return return_type

    def _check_overloaded_method_call(self, expr, struct_name, candidates,
                                      obj_type, type_subst):
        """Resolve and check a call to an overloaded instance method (design 55).

        Mirrors the singleton method tail but resolves the callee first and
        checks each argument exactly once (so a `move`/mutating argument is not
        double-processed). Design 105: a generic method overload may be selected
        by type-argument inference (the struct's own type substitution
        `type_subst` seeds the solve as the base substitution)."""
        arg_types = self._overload_arg_types(expr)
        method_info, mapping = self._resolve_overload(
            f"{struct_name}.{expr.method_name}", candidates, arg_types,
            self._has_explicit_type_args(expr), is_method=True,
            line=expr.line, column=expr.column,
            arguments=expr.arguments, expr=expr, base_subst=type_subst or {})
        if method_info is None:
            return None
        if method_info.mangled_name:
            expr.resolved_symbol = method_info.mangled_name
        offset = self._overload_cand_offset(method_info, is_method=True)
        self._stamp_overload_plan(expr, method_info.param_names[offset:], mapping)
        # Single chokepoint: effect edge to the resolved method.
        self._effect_call_method(
            method_info, f"`{struct_name}.{expr.method_name}`", expr.line)
        # Fold the method's OWN generic type params (inferred or explicit) into
        # the substitution alongside the struct's args (design 105).
        full_subst = dict(type_subst) if type_subst else {}
        # DF-216h: the WINNER's extension aliases (the representative's went in
        # upstream, and a mixed-rename overload set would need the winner's).
        if full_subst:
            self._receiver_type_subst(
                getattr(obj_type, 'symbol', None) or self.get_struct_info(struct_name),
                obj_type.type_args, method_info, full_subst)
        if method_info.type_params:
            for tp, ta in zip(method_info.type_params, expr.type_args or []):
                full_subst[tp.name] = self._resolve_type(ta)
            self._check_type_param_bounds(
                method_info.type_params, full_subst, expr.line, expr.column,
                callee_decl=method_info.ast_node,
                display=f"`{struct_name}.{expr.method_name}`")
        param_types = method_info.param_types[offset:]
        if full_subst:
            param_types = [t.substitute(full_subst) if t is not None else t
                           for t in param_types]
        self._finish_overloaded_args(expr, param_types, arg_types, mapping)
        self._reject_var_self_call_on_shared_self(expr, method_info)
        # design 260: the consuming-receiver funnel, entry point 1 of 2.
        self._check_consuming_receiver(expr, method_info)
        # `&var self` method may not be called on an immutable binding (L11).
        if getattr(method_info, "self_mutable", False) and not method_info.is_init:
            imm_root = self._immutable_receiver_root(expr.object)
            if imm_root is not None:
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot call `&var self` method `{expr.method_name}` on "
                    f"immutable variable `{imm_root}`",
                    expr.line, expr.column,
                    hint="consider using `var` instead of `let` to make it mutable",
                )
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping if self._call_has_labels(expr) else None,
            param_types, method_info.param_names[offset:])
        self._check_call_exclusivity(
            [a.value for a in expr.arguments], aligned_types,
            receiver=expr.object if not method_info.is_init else None,
            receiver_mutable=method_info.self_mutable,
            param_names=aligned_names,
        )
        return_type = method_info.return_type
        if full_subst and return_type is not None:
            return_type = return_type.substitute(full_subst)
        return return_type

    def _check_function_call(self, expr: FunctionCall) -> Optional[SawType]:
        """Check a function call."""
        # Atomic construction (design 41 item 4): `Atomic(<int>)`. A compiler-
        # known positional construction — the general struct-init path requires
        # named arguments, so intercept it here. v1 supports Atomic<Int> only.
        if expr.name == "Atomic" and not expr.type_args:
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`Atomic(...)` takes exactly one positional Int argument",
                    expr.line, expr.column
                )
                return None
            arg_type = self._check_expression(expr.arguments[0].value)
            if arg_type is not None and self._get_underlying_type(arg_type).kind != TypeKind.INT:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`Atomic(...)` expects an Int, got `{arg_type}`",
                    expr.line, expr.column
                )
            expr.is_atomic_construct = True
            return SawType(TypeKind.STRUCT, struct_name="Atomic",
                           type_args=[SawType(TypeKind.INT)])

        # Interior-cell construction (design 186): `UnsafeMutableInterior(v)`,
        # positional like `Atomic`/`UnsafeMemory` and intercepted for the same
        # reason — the general struct-init path wants named arguments, and the
        # cell's `value` field is a representation nobody writes at the source
        # level. `T` comes from the argument; the explicit
        # `UnsafeMutableInterior<T>(v)` spelling is accepted too, which is what a
        # generic body needs when the argument is itself a type parameter.
        if expr.name == "UnsafeMutableInterior":
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`UnsafeMutableInterior(...)` takes exactly one positional "
                    "value — the `T` the cell holds",
                    expr.line, expr.column
                )
                return None
            declared = (expr.type_args or [None])[0]
            if declared is not None:
                declared = self._resolve_type(declared)
                # Design 87: stamp the expectation before checking, so
                # `UnsafeMutableInterior<UInt8>(0)` types its literal `UInt8`.
                self._apply_literal_expected_type(expr.arguments[0].value, declared)
            arg_type = self._check_expression(expr.arguments[0].value)
            if declared is not None:
                # design 205: (source, target) — the argument flows INTO the
                # declared cell type, and only that direction may widen.
                if arg_type is not None and not self._transfer_compatible(
                        arg_type, declared):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`UnsafeMutableInterior<{declared}>(...)` was given a "
                        f"`{arg_type}`",
                        expr.line, expr.column
                    )
            cell_arg = declared if declared is not None else arg_type
            if cell_arg is None:
                return None
            expr.is_interior_cell_construct = True
            return SawType(TypeKind.STRUCT,
                           struct_name="UnsafeMutableInterior",
                           type_args=[cell_arg])

        # UnsafeMemory construction (design 46): `UnsafeMemory(<int>)` — a
        # compiler-known one-word wrapper over a fixed address. Like Atomic it is
        # positional, so intercept before the named struct-init path. The `T`/
        # `Use` come from the surrounding declared type (a static's annotation),
        # so a bare construction yields an un-parameterized `UnsafeMemory` that is
        # compatible with any `UnsafeMemory<T, Use>` target (the struct-arg
        # comparison treats an empty arg list as "matches any instantiation").
        # Explicit `UnsafeMemory<T, Use>(<int>)` is also accepted.
        if expr.name == "UnsafeMemory":
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`UnsafeMemory(...)` takes exactly one positional Int address",
                    expr.line, expr.column
                )
                return None
            arg_type = self._check_expression(expr.arguments[0].value)
            if arg_type is not None and self._get_underlying_type(arg_type).kind not in (
                    TypeKind.INT, TypeKind.UINT):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`UnsafeMemory(...)` expects an Int address, got `{arg_type}`",
                    expr.line, expr.column
                )
            expr.is_unsafe_mem_construct = True
            if expr.type_args:
                resolved = [self._resolve_type(t) for t in expr.type_args]
                result = SawType(TypeKind.STRUCT, struct_name="UnsafeMemory",
                                 type_args=resolved)
                self._validate_unsafe_memory_type(result, expr.line, expr.column)
                return result
            return SawType(TypeKind.STRUCT, struct_name="UnsafeMemory")

        if expr.name == "print":
            # design 137: `print(fmt, a, b)` renders each argument through its
            # own `Printable.format` into the `{}` slots. Monomorphized, not
            # varargs: arity is checked here against the literal format string.
            if len(expr.arguments) > 1:
                self._check_format_call("print", expr, expr.arguments[1:])
                return SawType(TypeKind.VOID)
            for arg in expr.arguments:
                arg_type = self._check_expression(arg.value)
                # Freestanding used to refuse a Float here for want of a dtoa
                # (design 20 item 2/4). Design 253 wrote one, in Saw, so the
                # profile question is gone — see `_check_format_call`.
                #
                # design 132 unit D: the same renderability question interpolation
                # asks. Codegen can lower a builtin or a Printable `to_string()`
                # and nothing else, so anything else was an ICE here (DF-128d /
                # DF-129a).
                if arg_type is not None:
                    self._check_renderable_operand(arg_type, arg.value,
                                                   "cannot print")
                    # design 135: a builtin argument formats into stack scratch,
                    # but a user `Printable` is rendered through the `to_string()`
                    # the compiler synthesizes here — an owned String the program
                    # never asked for. `print("{}", v)` streams the same bytes
                    # through the value's own `format` and allocates nothing.
                    if (self._hidden_alloc_gate()
                            and self._get_underlying_type(arg_type).kind
                            not in self._RENDERABLE_BUILTIN_KINDS):
                        self._hidden_alloc_error(
                            f"`print` renders `{arg_type}` through `to_string()`, "
                            f"which allocates a String",
                            arg.value.line, arg.value.column,
                            hint="write `print(\"{}\", value)` — the "
                                 "format-argument spelling streams the value "
                                 "through its own `format` into stack scratch")
            return SawType(TypeKind.VOID)
        if expr.name == "panic":
            # design 49 item 1: panic(message: String) -> Never. Emits `message`
            # (plus a newline) through the saw_panic seam and does not return.
            # Its type is NEVER (the bottom type): control never continues past
            # it, so a function body ending in `panic(...)` needs no return value
            # and the value is assignable to any expected type.
            if len(expr.arguments) > 1:
                # design 137: `panic("out of {}", what)` assembles the message
                # in stack scratch, so a panic can still say what happened with
                # the allocator refusing everything.
                self._check_format_call("panic", expr, expr.arguments[1:])
            elif len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`panic` takes a String message, optionally followed by "
                    "format arguments for its `{}` placeholders",
                    expr.line, expr.column
                )
            else:
                msg_type = self._check_expression(expr.arguments[0].value)
                if (msg_type is not None
                        and self._get_underlying_type(msg_type).kind != TypeKind.STRING):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`panic` expects a String message, got `{msg_type}`",
                        expr.arguments[0].value.line, expr.arguments[0].value.column
                    )
            return SawType(TypeKind.NEVER)
        if expr.name == "assert":
            # design 49 item 2: assert(cond: Bool, message: String). A no-op when
            # `cond` is true; on false it panics with
            # "assertion failed: {message} (line N)" through the same seam (the
            # call-site line N is available on the AST node, so it is included).
            # `debug_assert` is deferred — there is no build-profile split yet.
            if len(expr.arguments) > 2:
                # design 137: `assert(ok, "want {} got {}", a, b)` — the message
                # is assembled only on the failing branch, and only then.
                cond_type = self._check_expression(expr.arguments[0].value)
                if (cond_type is not None
                        and self._get_underlying_type(cond_type).kind != TypeKind.BOOL):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`assert` expects a Bool condition, got `{cond_type}`",
                        expr.arguments[0].value.line, expr.arguments[0].value.column
                    )
                self._check_format_call("assert", expr, expr.arguments[2:],
                                        fmt_index=1)
            elif len(expr.arguments) != 2 or any(a.name is not None for a in expr.arguments):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`assert` takes a Bool condition and a String message, "
                    "optionally followed by format arguments for its `{}` "
                    "placeholders",
                    expr.line, expr.column
                )
            else:
                cond_type = self._check_expression(expr.arguments[0].value)
                if (cond_type is not None
                        and self._get_underlying_type(cond_type).kind != TypeKind.BOOL):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`assert` expects a Bool condition, got `{cond_type}`",
                        expr.arguments[0].value.line, expr.arguments[0].value.column
                    )
                msg_type = self._check_expression(expr.arguments[1].value)
                if (msg_type is not None
                        and self._get_underlying_type(msg_type).kind != TypeKind.STRING):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`assert` expects a String message, got `{msg_type}`",
                        expr.arguments[1].value.line, expr.arguments[1].value.column
                    )
            return SawType(TypeKind.VOID)
        if expr.name in ("__saw_test_suspend", "__saw_suspend"):
            # design 22: `__saw_test_suspend` — compiler-known synthetic suspension
            # point, effect-only (feeds the suspendability inference; codegen is a
            # no-op; NO state-machine transform — that is design-22's scope guard).
            # design 44: `__saw_suspend` — the coroutine-transform state boundary. It
            # is ALSO an effect source, but inside a DRIVEN function (reached from
            # a `__saw_drive` site) the transform splits the body at it. Outside any
            # driven closure it lowers to the same no-op, so a lone `__saw_suspend`
            # behaves exactly like `__saw_test_suspend` (effect-suspending, runs).
            # Both take no arguments and return Void.
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`{expr.name}` takes no arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            self._effect_direct_source(expr.name, expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "yield_now":
            # design 45 item 4: cooperative yield — a real suspension point that
            # hands control back to the executor and is immediately re-ready. Like
            # `__saw_suspend`, it is an effect source and a transform state boundary,
            # but it carries a "ready" wake reason (the executor reschedules it at
            # once). Takes no arguments; returns Void.
            #
            # design 114: the bare `yield_now` name is a stdlib-INTERNAL intrinsic.
            # std bodies (channel/net/taskgroup — checked with `_checking_builtins`)
            # and synthesized coro output reach it directly. User code reaches the
            # yield only through std.task's `public func yield_now()` wrapper, which
            # is un-gated by `import std.task` (its name then sits in
            # `directly_accessible`); a call to that wrapper lands HERE with the
            # name accessible, so it lowers to the exact same intrinsic (no extra
            # frame — the wrapper is transparent). A bare, un-imported use is a clean
            # error naming the replacement.
            # `--runtime-build` (design 113b) loads NO std, so std.task does not
            # exist to import — the bare intrinsic stays reachable there (a seam
            # body that suspends is caught by the separate `@export`-suspend rule).
            if not (getattr(self, '_checking_builtins', False)
                    or getattr(self, 'runtime_build', False)
                    or self._in_synthesized_context()
                    or "yield_now" in self.namespace.directly_accessible):
                self._error(
                    ErrorKind.UNDEFINED_FUNCTION,
                    "`yield_now` is a stdlib-internal cooperative-yield intrinsic "
                    "and cannot be called bare",
                    expr.line, expr.column,
                    hint="add `import std.task` and call its public `yield_now()`")
                return SawType(TypeKind.VOID)
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`yield_now` takes no arguments, but {len(expr.arguments)} "
                    f"were given", expr.line, expr.column)
            self._effect_direct_source("yield_now", expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "__saw_io_park":
            # design 76 (A4): the IO reactor's suspension boundary. Like
            # `yield_now`, a suspension point + transform state boundary, but it
            # carries an IO-PARK wake reason (a negative sentinel): the executor
            # parks in the reactor (kqueue/epoll) until an fd is ready rather than
            # busy-requeuing. Emitted only inside std/net.saw's would-block loops;
            # reached as a plain call (no executor) it is a no-op. No arguments.
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`__saw_io_park` takes no arguments, but {len(expr.arguments)} "
                    f"were given", expr.line, expr.column)
            self._effect_direct_source("__saw_io_park", expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "__saw_chan_park":
            # design 230: park on a READINESS WORD. Like `__saw_io_park` a
            # suspension point and a transform state boundary, but it carries the
            # word's NEGATED ADDRESS as its wake reason (the one argument), so the
            # executor knows which frame to leave alone and what to watch for it.
            # Emitted only by std/channel.saw's `receive()` and by the coroutine
            # transform's inline receive lowering; reached as a plain call (no
            # executor) it routes to the same `__saw_exec_park` the io fallback
            # does. One `Int` argument.
            if len(expr.arguments) != 1:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`__saw_chan_park` takes one argument, but "
                    f"{len(expr.arguments)} were given", expr.line, expr.column)
            else:
                self._check_expression(expr.arguments[0].value)
            self._effect_direct_source("__saw_chan_park", expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "io_wait":
            # design 76 (A4): the user-facing IO suspension point. `io_wait(fd,
            # write)` registers `fd` with the reactor for read (write==0) or write
            # (write==1) interest and parks the task until the fd is ready. A real
            # suspension source (so callers suspend and a suspending `main` gets the
            # entry executor). Two Int args; returns Void.
            if len(expr.arguments) != 2:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`io_wait` takes exactly two positional Int arguments "
                    f"(fd, write), but {len(expr.arguments)} were given",
                    expr.line, expr.column)
            else:
                for a in expr.arguments:
                    at = self._check_expression(a.value)
                    if at is not None and self._get_underlying_type(at).kind != TypeKind.INT:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"`io_wait` expects Int arguments, got `{at}`",
                            expr.line, expr.column)
            self._effect_direct_source("io_wait", expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "io_unwait":
            # DF-134a: the inverse of `io_wait` — drop the readiness interest
            # `io_wait(fd, write)` armed. NOT a suspension source: it neither
            # parks nor yields, so a `sync` caller may use it and a park loop can
            # call it on the way out of its cancellation exit. Two Int args,
            # returns Void. Idempotent at the seam, so calling it when nothing is
            # armed is well defined.
            if len(expr.arguments) != 2:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`io_unwait` takes exactly two positional Int arguments "
                    f"(fd, write), but {len(expr.arguments)} were given",
                    expr.line, expr.column)
            else:
                for a in expr.arguments:
                    at = self._check_expression(a.value)
                    if at is not None and self._get_underlying_type(at).kind != TypeKind.INT:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"`io_unwait` expects Int arguments, got `{at}`",
                            expr.line, expr.column)
            return SawType(TypeKind.VOID)
        if expr.name == "__saw_blk_start":
            # design 103 (A6): the blocking-extern offload START intrinsic, emitted
            # by the coro transform. Its argument is syntactically a call to the
            # blocking extern (`slow(arg)`), but the offload does NOT call it inline —
            # it hands the extern's ADDRESS + the arg to the runtime thread. So we
            # type-check only the inner argument expressions and deliberately do NOT
            # record the blocking suspension effect (the real suspension is the
            # `io_wait` the transform emits between start and take, which keeps the
            # synthesized `resume` method suspension-free of the blocking source).
            # Returns the job handle as an Int. Compiler-generated only.
            if len(expr.arguments) == 1:
                inner = expr.arguments[0].value
                for a in getattr(inner, 'arguments', []):
                    self._check_expression(a.value)
            return SawType(TypeKind.INT)
        if expr.name in ("__saw_blk_done", "__saw_blk_pipe_fd", "__saw_blk_take"):
            # design 103 (A6): the offload done-poll / pipe-fd / join+take intrinsics.
            # Each takes the job handle (Int); done/pipe_fd answer a flag and an fd.
            # None is a suspension source. Compiler-generated only.
            if len(expr.arguments) == 1:
                self._check_expression(expr.arguments[0].value)
            # design 183 unit 2: `take` yields the EXTERN's result, whatever type
            # the declaration gives it — the job carries one word and codegen
            # marshals it back. Typing it `Int` unconditionally is what pinned the
            # old offload to `(Int) -> Int`.
            blk = getattr(expr, 'blk_extern', None)
            if expr.name == "__saw_blk_take" and blk is not None:
                sym = self.get_function_info(blk)
                if sym is not None and sym.return_type is not None:
                    return sym.return_type
            return SawType(TypeKind.INT)
        if expr.name == "sleep":
            # design 45 item 4 / design 180: cooperative timed wait — a
            # suspension point carrying a "sleep this long" wake reason the
            # executor honours before resuming. Takes exactly one `Duration`
            # (prelude, std/duration.saw); returns Void. The bare-Int form is
            # GONE: a naked number carries no unit, and the one it silently
            # meant could not express a span past about 35 minutes (DF-170a).
            hint = ("a span is a `Duration`: `sleep(Duration.ms(200))`, or "
                    "`Duration.ns` / `us` / `secs`")
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`sleep` takes exactly one positional `Duration` argument",
                    expr.line, expr.column, hint=hint)
            else:
                arg_type = self._check_expression(expr.arguments[0].value)
                if arg_type is not None:
                    resolved = self._get_underlying_type(arg_type)
                    if not (resolved.kind == TypeKind.STRUCT
                            and resolved.struct_name == "Duration"):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"`sleep` expects a `Duration`, got `{arg_type}`",
                            expr.line, expr.column, hint=hint)
            self._effect_direct_source("sleep", expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "__saw_bt_table":
            # design 158: the address of this program's in-binary backtrace
            # table. Saw cannot name an extern global (DF-113a), and the table's
            # size is only known once every frame's layout is fixed, so it is
            # reached as an intrinsic rather than as a declared symbol. Takes no
            # arguments; NOT a suspension source (the panic-time walker calls it
            # from a `sync` context).
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`__saw_bt_table` takes no arguments",
                    expr.line, expr.column)
            return SawType(TypeKind.POINTER,
                           inner_type=SawType(TypeKind.UINT8))
        if expr.name == "__saw_box_data":
            # design 52b item 2: extract the data word (i8*) of a `Box<any T>` fat
            # pointer — the address of the erased heap payload. The synthesized
            # `__spawn_<f>` uses it to point a `Task` at the boxed frame's
            # `__result` / `__cancel` slots. Compiler-generated only; the argument
            # is a reference to the box. NOT a suspension source.
            if len(expr.arguments) == 1:
                self._check_expression(expr.arguments[0].value)
            return SawType(TypeKind.POINTER,
                           inner_type=SawType(TypeKind.INT8))
        if expr.name == "cancelled":
            # design 52b item 3: read the CURRENT task's cooperative cancel flag.
            # Inside a driven/spawned body the coro transform rewrites this to the
            # frame's `__cancel` word; outside any frame it lowers to `false` (no
            # task to cancel). Takes no arguments; returns Bool; NOT a suspension
            # source (a cancel check must be callable in any context).
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`cancelled` takes no arguments, but {len(expr.arguments)} "
                    f"were given", expr.line, expr.column)
            return SawType(TypeKind.BOOL)
        if expr.name in ("__saw_drive", "__saw_drive_steps"):
            # design 44: the test-only executor entry. `__saw_drive(f(args))` creates
            # a frame for the suspending call `f(args)`, drives it to completion,
            # and yields f's result; `__saw_drive_steps(f(args))` yields the number of
            # suspensions observed (an Int). It ABSORBS the callee's suspension —
            # the enclosing function does NOT become suspending — which is how a
            # non-suspending `main` can drive a coroutine with no executor yet.
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`{expr.name}(...)` takes exactly one positional argument: a "
                    f"call to a suspending function",
                    expr.line, expr.column
                )
                return None
            inner = expr.arguments[0].value
            from ast_nodes import FunctionCall as _FC, MethodCall as _MC
            if not isinstance(inner, (_FC, _MC)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{expr.name}(...)` expects a direct call to a suspending "
                    f"function or method, e.g. `{expr.name}(work())` or "
                    f"`{expr.name}(obj.step())`",
                    expr.line, expr.column
                )
                return None
            mode = "value" if expr.name == "__saw_drive" else "steps"
            # Before anything reads the callee: put the AUTHORED name back if an
            # earlier pass over this same AST already monomorphized it.
            self._restore_authored_call(inner)
            # Type-check the inner call inside an absorbing scope so its suspend
            # edge does not taint the caller. This also stamps inner.resolved_type
            # and validates the argument types.
            sentinel = self._effect_absorb_scope()
            inner_type = self._check_expression(inner)
            self._effect_unabsorb(sentinel)
            driven = getattr(inner, 'method_name', None) or getattr(inner, 'name', '?')
            if self._reject_never_task_body(
                    f"`{driven}`",
                    f"`{expr.name}` would drive it for ever", inner_type,
                    expr.line, expr.column):
                return None
            if isinstance(inner, _MC):
                # design 45 Part 0c: driving a suspending method. The receiver's
                # struct type names the driven-method root; the transform builds a
                # frame holding a `__recv` pointer into the receiver's storage.
                recv_type = getattr(inner.object, 'resolved_type', None)
                struct_name = getattr(recv_type, 'struct_name', None) if recv_type else None
                # DF-184a: a STATIC method is driven by the same machinery — its
                # frame simply has no receiver pointer. The owning type's name is
                # stamped on the CALL, since there is no receiver expression to
                # read it off.
                if struct_name is None and getattr(
                        inner, 'is_static_method_call', False):
                    struct_name = getattr(inner, 'static_receiver', None)
                if struct_name is None:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`{expr.name}(...)` on a method requires a concrete struct "
                        f"receiver", expr.line, expr.column)
                    return inner_type if inner_type is not None else SawType(TypeKind.VOID)
                # design 70 (A5): a generic method (its own type params) is
                # monomorphized to a concrete method before frame synthesis.
                # design 74 (A5-rest, shape 2): a method on a GENERIC struct
                # (`Holder<T>`) driven for a concrete receiver `Holder<Int>` is
                # monomorphized over the STRUCT's type params so the frame's
                # `__recv` gets a concrete layout.
                struct_sym = self.namespace.lookup_struct(struct_name)
                struct_is_generic = (
                    struct_sym is not None and bool(struct_sym.type_params)
                    and bool(getattr(recv_type, 'type_args', None)))
                # design 104 item 3: a method that is BOTH struct-generic and
                # method-generic routes to the generic-STRUCT path (it monomorphizes
                # over the struct's type params AND the method's own type args). Only
                # a method-generic method on a NON-generic struct takes the
                # method-only path.
                if getattr(inner, 'type_args', None) and not struct_is_generic:
                    self._drive_generic_method(inner, struct_name, mode, expr)
                elif struct_is_generic:
                    self._drive_generic_struct_method(
                        inner, struct_name, recv_type, mode, expr)
                else:
                    # design 95: pass the resolved-signature symbol so an
                    # overloaded suspending method driven directly keys its own frame.
                    self._effect_record_driven_method(
                        struct_name, inner.method_name, mode,
                        resolved_symbol=getattr(inner, 'resolved_symbol', None))
            else:
                # design 70 (A5): driving a generic free function. Monomorphize the
                # instantiation to a concrete function keyed by the mangled symbol,
                # record it as the driven root, and rewrite the inner call so the
                # coroutine transform sees an ordinary non-generic call.
                if getattr(inner, 'type_args', None):
                    resolved_args = [self._resolve_type(a) for a in inner.type_args]
                    if not all(self._is_concrete_type(a) for a in resolved_args):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"`{expr.name}(...)` of a generic function requires "
                            f"concrete type arguments (cannot drive an instantiation "
                            f"whose type arguments are themselves type parameters)",
                            inner.line, inner.column)
                    else:
                        # Design 105: drive from the resolved overload's `$OL$`
                        # base template when present (generic overload), else the
                        # plain name (lone generic).
                        tmpl = getattr(inner, 'resolved_symbol', None) or inner.name
                        mangled = self._effect_queue_fn_mono(tmpl, resolved_args)
                        self._effect_record_driven(mangled, mode)
                        inner.name = mangled
                        inner.type_args = None
                else:
                    self._effect_record_driven(inner.name, mode)
            if expr.name == "__saw_drive_steps":
                return SawType(TypeKind.INT)
            return inner_type if inner_type is not None else SawType(TypeKind.VOID)
        if expr.name == "spawn":
            # design 242 unit 1: the bare form is RETIRED. No deprecation alias —
            # the namespace is what says which engine a call site is on, and the
            # old spelling said neither.
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                "`spawn { ... }` no longer names an engine",
                expr.line, expr.column,
                hint="write `Thread.spawn { ... }` for an OS thread (blocking, "
                     "`join()` waits), or spawn into a `TaskGroup` with "
                     "`group.spawn(work(...))` for a cooperative task"
            )
            return None
        if expr.name == "Thread.spawn":
            return self._check_spawn(expr)
        if expr.name == "Task.spawn":
            return self._check_task_spawn(expr)
        if expr.name == "sizeof":
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`sizeof` takes no arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            if not expr.type_args or len(expr.type_args) != 1:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "`sizeof` requires exactly one type argument: sizeof<T>()",
                    expr.line, expr.column
                )
                return None
            resolved_type = self._resolve_type(expr.type_args[0])
            if resolved_type is None:
                return None
            return SawType(TypeKind.INT)
        if expr.name == "alignof":
            # Sibling of sizeof<T>(): the ABI alignment (in bytes) of type T for
            # the compilation target. Same plumbing — a typechecker special-case
            # that validates arity/type-arg and yields Int; codegen lowers it via
            # llvmlite target data. Used by alloc-layer stdlib (Vector) to request
            # correctly-aligned buffers from the allocator instead of a hardcoded
            # constant.
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`alignof` takes no arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            if not expr.type_args or len(expr.type_args) != 1:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "`alignof` requires exactly one type argument: alignof<T>()",
                    expr.line, expr.column
                )
                return None
            resolved_type = self._resolve_type(expr.type_args[0])
            if resolved_type is None:
                return None
            return SawType(TypeKind.INT)
        if expr.name == "__saw_deinit_in_place":
            # Compiler-internal drop intrinsic for stdlib container code: run the
            # cleanup (drop glue) for the value at an UnsafePointer<T>, in place.
            # Manual `deinit()` calls are banned language-wide; this escape hatch
            # is gated to `deinit` method bodies so a container (Vector/Map) can
            # release its live elements before freeing its buffer, and cannot be
            # used as a general user-facing manual-deinit unlock.
            cur = getattr(self, 'current_method', None)
            if cur is None or getattr(cur, 'name', None) != "deinit":
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "`__saw_deinit_in_place` is a compiler-internal intrinsic usable "
                    "only inside a `deinit` method body",
                    expr.line, expr.column
                )
                return SawType(TypeKind.VOID)
            if len(expr.arguments) != 1:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`__saw_deinit_in_place` takes exactly one pointer argument, but "
                    f"{len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return SawType(TypeKind.VOID)
            arg_type = self._check_expression(expr.arguments[0].value)
            if arg_type is not None:
                arg_underlying = self._get_underlying_type(arg_type)
                if arg_underlying.kind != TypeKind.POINTER:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`__saw_deinit_in_place` expects an `UnsafePointer<T>` argument, "
                        f"got `{arg_type}`",
                        expr.line, expr.column
                    )
            return SawType(TypeKind.VOID)
        if expr.name == "__saw_forget":
            # design 45 (Part 0a): compiler-internal clear-without-drop for an
            # optional lvalue. Overwrites the optional's `is_some` discriminant to
            # None WITHOUT running the inner value's drop glue — the frame-resident
            # drop-flag clear that a conditional `move` of a cleanup-needing frame
            # local needs (assignment can't express it, since assigning None drops
            # the old inner). Generated only by the coroutine transform; never
            # user-facing (no diagnostic surface required beyond arity). No effect
            # source: clearing a flag never suspends.
            if len(expr.arguments) != 1:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`__saw_forget` takes exactly one argument, but "
                    f"{len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return SawType(TypeKind.VOID)
            self._check_expression(expr.arguments[0].value)
            return SawType(TypeKind.VOID)
        var_info = self.current_scope.lookup(expr.name)
        # design 226: calling a `FuncPointer<F>` is an ordinary call expression
        # on the value, checked against `F` exactly as a closure value is
        # checked against its own function type — same arity rule, same
        # structural (unlabeled) argument rule, same value-transfer checkpoint,
        # same exclusivity check. The ONE difference is at the ABI, and that is
        # codegen's: no environment travels with it.
        fp_sig = (self._funcpointer_signature(var_info.type)
                  if var_info is not None else None)
        if var_info and (var_info.type.kind == TypeKind.FUNCTION
                         or fp_sig is not None):
            func_type = fp_sig if fp_sig is not None else var_info.type
            callee = ("function pointer" if fp_sig is not None else "closure")
            # Design 66: closure/function-value types are STRUCTURAL — they carry
            # no parameter names, so a labeled call through one has nothing to
            # bind to.
            if self._call_has_labels(expr):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"labeled arguments are not allowed when calling through the "
                    f"{callee} value `{expr.name}` ({callee} types are structural)",
                    expr.line, expr.column)
                return func_type.func_return_type or SawType(TypeKind.VOID)
            # design 22: a call through a function-typed value. If the value's
            # type is not `sync`, the caller conservatively suspends.
            self._effect_indirect_call(func_type, expr.line)
            param_types = func_type.param_types or []
            return_type = func_type.func_return_type or SawType(TypeKind.VOID)
            if len(expr.arguments) != len(param_types):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"{callee} takes {len(param_types)} argument(s), but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return return_type
            for i, (arg, expected_type) in enumerate(zip(expr.arguments, param_types)):
                if isinstance(arg.value, ClosureExpr):
                    arg_type = self._check_closure(arg.value, expected_type, as_call_argument=True)
                else:
                    self._apply_literal_expected_type(arg.value, expected_type)
                    arg_type = self._check_expression(arg.value)
                if arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"argument {i + 1} expects `{expected_type}` but got `{arg_type}`",
                        arg.value.line, arg.value.column,
                        hint=self._int_conversion_hint(arg_type, expected_type)
                    )
                # Design 87: literal fixed-width adoption + range check ran in the
                # `_apply_literal_expected_type` propagation above (before the arg
                # check) — the per-position range check here is subsumed.
                self._check_value_transfer(arg.value, expected_type, "call argument",
                                           arg.value.line, arg.value.column)
            self._check_call_exclusivity([a.value for a in expr.arguments], param_types)
            return return_type
        # Overloading (design 55): a name with 2+ visible overloads resolves
        # through the exact-match resolver, which then feeds the SAME downstream
        # machinery (value-transfer checkpoint, effect edges, exclusivity) with
        # the resolved callee.
        overloads = self.namespace.lookup_function_overloads(
            expr.name, accessor_module=self._accessor_vis_module())
        if len(overloads) > 1 and self.namespace.is_accessible(expr.name):
            return self._check_overloaded_function_call(expr, overloads)
        # Prelude discipline (design 82 Part B): a bare call to a non-prelude std
        # free function not imported here errors with an import hint.
        if (expr.name in getattr(self, '_std_symbol_file', {})
                and self._std_name_gated(expr.name, expr.line, expr.column)):
            return None
        func_info = self.get_function_info(expr.name)
        if func_info and not self.namespace.is_accessible(expr.name):
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"function `{expr.name}` is not directly accessible",
                expr.line, expr.column,
                hint=f"use qualified access (e.g., `module_name.{expr.name}`) or import it directly"
            )
            return None
        if not func_info:
            # A function a module this file imports HAS, and this file did not
            # bind. DF-247b widened the walk from `modules` to
            # `imported_search_sources`: a selective import no longer binds a
            # qualifier, so the module it named would otherwise stop being
            # findable here — and this is the diagnostic whose whole job is to
            # say which module has the name.
            #
            # The advice follows the amendment. The qualified spelling is only
            # available where a whole-module import bound the qualifier, so a
            # file that reached this module through braces or a glob is told to
            # SELECT the name (the smaller edit, and the one its import list
            # already documents), with the whole-module line as the other out.
            from namespace import SymbolKind
            for module_name, module_ns in self.namespace.imported_search_sources():
                # design 229: not through a module that merely imports it.
                if module_ns.hidden_import(expr.name):
                    continue
                sym = module_ns.lookup_function(expr.name)
                if sym and sym.visibility == Visibility.PUBLIC:
                    qualifier = self.namespace.modules.get(module_name)
                    if qualifier is not None:
                        hint = (f"use qualified access "
                                f"(`{module_name}.{expr.name}`), or select it "
                                f"with `import {module_name}.{{{expr.name}}}`")
                    else:
                        # The qualifier a whole-module import binds is the LAST
                        # path segment, which is what the reader would write.
                        leaf = module_name.rsplit('.', 1)[-1]
                        hint = (f"select it with "
                                f"`import {module_name}.{{{expr.name}}}`, or "
                                f"add `import {module_name}` to write "
                                f"`{leaf}.{expr.name}`")
                    self._error(
                        ErrorKind.UNDEFINED_FUNCTION,
                        f"function `{expr.name}` is not directly accessible",
                        expr.line, expr.column,
                        hint=hint
                    )
                    return None
            # `UserId(42)` — the explicit crossing INTO a distinct alias
            # (design 63). Checked before the struct branch below because an
            # alias name is resolved by its own lookup, not by struct info.
            alias_info = self.get_type_alias_info(expr.name)
            if alias_info is not None:
                return self._check_alias_construction(expr, alias_info)
            if self.get_struct_info(expr.name) and self.namespace.is_accessible(expr.name):
                from ast_nodes import StructInit, Argument
                field_inits = []
                for arg in expr.arguments:
                    if arg.name:
                        field_inits.append((arg.name, arg.value))
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"struct initialization requires named arguments",
                            arg.value.line, arg.value.column
                        )
                        return None
                struct_init = StructInit(
                    struct_name=expr.name,
                    field_inits=field_inits,
                    type_args=expr.type_args,
                    line=expr.line,
                    column=expr.column
                )
                result = self._check_struct_init(struct_init)
                # The canonicalized argument list belongs to the CALL node too:
                # codegen monomorphizes from this one, and design 37's
                # default-filling / design 148's const fold both happen on the
                # StructInit copy. A bare-name const argument (DF-172j
                # `FixedBuf<CAP>`) becomes a number exactly here, so without the
                # write-back codegen would still see the name.
                if struct_init.type_args:
                    expr.type_args = struct_init.type_args
                expr.resolved_init_params = struct_init.resolved_init_params
                # Design 53: a matched init may have appended default-valued named
                # arguments; carry the augmented field-init list to codegen, which
                # otherwise rebuilds it from the (possibly empty) argument list.
                expr.resolved_field_inits = struct_init.field_inits
                # Design 144: `_check_struct_init` canonicalized the name it was
                # handed; carry that identity to codegen, which otherwise routes
                # `Bag()` by the written name and finds no layout under it.
                expr.resolved_type_identity = struct_init.struct_name
                return result
            # `A()` — constructing a value of an in-scope type parameter (design
            # 37). The allocator model relies on this: inside `Vector<T, A>`, the
            # container writes `A().alloc(...)` and monomorphization lowers `A`
            # to the concrete zero-sized allocator (`Global`, `LoudAlloc`), so
            # the construction becomes a direct zero-size placeholder and the
            # `.alloc`/`.dealloc` calls dispatch statically. The value's type is
            # the type parameter itself, kept abstract for the body check; a
            # trait method on it resolves through the parameter's bounds
            # (`_check_type_param_method_call`).
            type_params = getattr(self, 'current_type_params', {})
            if expr.name in type_params:
                if expr.arguments:
                    self._error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"constructing a value of type parameter `{expr.name}` "
                        f"takes no arguments",
                        expr.line, expr.column
                    )
                return SawType(TypeKind.STRUCT, struct_name=expr.name)
            # design 229: same teaching case as the struct-init path — a name a
            # module this file imports has and does not re-export.
            if self._report_bare_not_reexported(expr.name, expr.line,
                                                expr.column):
                return None
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"undefined function `{expr.name}`",
                expr.line, expr.column
            )
            return None
        # design 53: an aliased selective import (`import m.{add as plus}`)
        # registers a symbol carrying its real codegen name in `mangled_name`;
        # stamp it so codegen calls the real definition, not the alias.
        if func_info.mangled_name:
            expr.resolved_symbol = func_info.mangled_name
        # design 22: record the call edge in the suspend graph (blocking externs
        # are a direct suspension source; other calls are edges to their node).
        self._effect_call_function(func_info, expr.name, expr.line)
        if func_info.type_params:
            # design 93: infer omitted type arguments from the argument types
            # (a partial explicit prefix pins its parameters, the rest infer).
            # Explicit-and-complete keeps the exact legacy path below.
            if len(expr.type_args or []) < len(func_info.type_params):
                # Design 105: map arguments to parameters BY LABEL before
                # unification, so a labeled/out-of-order call infers correctly.
                infer_mapping = self._infer_label_mapping(
                    expr, func_info.param_names, func_info.default_values)
                full = self._solve_call_type_args(
                    func_info.type_params, func_info.param_types, expr,
                    infer_mapping, {}, expr.type_args, f"function `{expr.name}`",
                    expr.line, expr.column,
                    default_values=func_info.default_values)
                if full is None:
                    return None
                expr.type_args = [full[tp.name] for tp in func_info.type_params]
            if len(expr.type_args) != len(func_info.type_params):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{expr.name}` expects {len(func_info.type_params)} type argument(s), "
                    f"but {len(expr.type_args)} were given",
                    expr.line, expr.column
                )
                return None
            type_map: Dict[str, SawType] = {}
            for type_param, type_arg in zip(func_info.type_params, expr.type_args):
                resolved_arg = self._resolve_type(type_arg)
                type_map[type_param.name] = resolved_arg
                for bound in type_param.bounds:
                    if self.get_trait_info(bound) is None:
                        self._error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"unknown trait `{bound}` in type parameter bound",
                            expr.line, expr.column,
                            hint=self._retired_trait_hint(bound)
                        )
                        continue
                    concrete_type_name = None
                    if resolved_arg.kind == TypeKind.STRUCT:
                        concrete_type_name = resolved_arg.struct_name
                    elif resolved_arg.kind == TypeKind.ENUM:
                        concrete_type_name = resolved_arg.enum_name
                    if bound in self._COPY_BOUND_NAMES:
                        # EVERY Copy-family bound goes through `_bound_satisfied`
                        # (design 219). It used to be `Copy` alone, with
                        # `Copy` and `ExplicitCopy` falling through to the
                        # raw conformance lookup below — which is why `T:
                        # Copy` rejected `Int` and an auto-tier struct:
                        # a DECLARATION was demanded for a tier that owes none.
                        # One entry point now answers all three, from the tier.
                        if not self._bound_satisfied(resolved_arg, bound):
                            if bound == "ExplicitCopy":
                                hint = (f"add `@synthesize extension "
                                        f"{concrete_type_name}: ExplicitCopy {{}}`"
                                        if concrete_type_name else
                                        "the type must be duplicable: on the "
                                        "`Copy` tier, or declaring `ExplicitCopy`")
                            else:
                                hint = ("the `Copy` tier is what duplicates "
                                        "silently — a trivially-copyable type, or "
                                        "one whose members the compiler retains; a "
                                        "type that copies only with a spelled "
                                        "`.copy()` needs an `ExplicitCopy` bound "
                                        "here instead")
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not satisfy the `{bound}` bound",
                                expr.line, expr.column,
                                hint=hint
                            )
                    elif bound in ("Send", "Sync"):
                        # Send/Sync are structural marker traits (design 21 item 1),
                        # never explicit conformances. `_bound_satisfied` also honors
                        # an abstract type parameter's own declared bounds.
                        if not self._bound_satisfied(resolved_arg, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not satisfy the `{bound}` bound",
                                expr.line, expr.column,
                                hint="Send/Sync are derived structurally; a field or payload of this type is not "
                                     + bound
                            )
                    elif bound == "Equatable":
                        # Equatable is structural (design 32): primitives + String,
                        # trivial (POD) structs and payload-free enums, plus any
                        # declared conformer all satisfy it without a registered
                        # conformance record.
                        if not self._bound_satisfied(resolved_arg, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not satisfy the `Equatable` bound",
                                expr.line, expr.column,
                                hint=f"add `extension {concrete_type_name}: Equatable {{}}`"
                                     if concrete_type_name else None
                            )
                    elif (resolved_arg.kind == TypeKind.STRUCT
                          and resolved_arg.struct_name
                          in getattr(self, 'current_type_params', {})):
                        # The callee's bound is applied to an ABSTRACT type
                        # parameter of the enclosing generic (`inner<T>(w)` inside
                        # `middle<T: Seed>`). It is satisfied exactly when the
                        # caller's own declared bounds carry it — a bounds-
                        # environment lookup; we cannot resolve `T` structurally
                        # here (design 77 item 2).
                        if not self._bound_satisfied(resolved_arg, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type parameter `{resolved_arg}` does not satisfy the `{bound}` bound",
                                expr.line, expr.column,
                                hint=f"add the bound to the enclosing signature: "
                                     f"`<{resolved_arg.struct_name}: {bound}>`"
                            )
                    elif concrete_type_name:
                        # DF-150b: ask the query that WALKS imported modules.
                        # `get_conformances` reads only this namespace's own
                        # table, so a conformance declared in the module that
                        # defines the type was invisible unless an import had
                        # copied it in — which the glob and selective forms do
                        # and a qualifier binding does not. Design 142 makes a
                        # conformance coherent program-wide and visible wherever
                        # the type and the trait are, so the import form must not
                        # decide the answer. The inference path beside this one
                        # already used the walking query (`_bound_satisfied`).
                        if not self.namespace.type_conforms_to(
                                concrete_type_name, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not implement trait `{bound}`",
                                expr.line, expr.column,
                                hint=f"add `extension {concrete_type_name}: {bound} {{ ... }}`"
                            )
                        else:
                            type_assigns = self.namespace.get_type_assignments(concrete_type_name, bound)
                            for assoc_name, assoc_type in type_assigns.items():
                                type_map[assoc_name] = assoc_type
                    else:
                        # Design 109: a type argument with no struct/enum name to
                        # key a conformance by — a primitive, tuple, Optional,
                        # closure, or existential — was previously left UNCHECKED
                        # for the non-structural / user-trait bounds (silent accept
                        # of an invalid program). Route it through the same
                        # `_bound_satisfied` / conformance registry the trait-method
                        # dispatch and the generic-method path use: a structural
                        # trait (Comparable/Hashable/Printable) is satisfied where
                        # the primitive structurally conforms; a user trait is
                        # satisfied only via a registered `extension Int: T`.
                        if not self._bound_satisfied(resolved_arg, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not satisfy the `{bound}` bound",
                                expr.line, expr.column)
            # design 219 wave C: discharge entry point 1 (the free-function
            # generic path). Declared bounds are checked above; the INFERRED
            # tier requirement is recorded here and resolved at finalize.
            self._tier_record_obligation(
                func_info.ast_node, func_info.type_params, type_map,
                f"`{expr.name}`", expr.line, expr.column)
            self._tier_check_instance_unsafe(
                func_info, f"`{expr.name}`", type_map, expr.line, expr.column)
            # design 70 (A5): record a deferred effect edge to this instantiation.
            # Materialized at finalize only if `expr.name`'s template is
            # effect-polymorphic (calls a method on a type-param receiver), so an
            # instantiation whose concrete `T` suspends taints its caller / trips a
            # sync context, while ordinary generic calls stay untouched. Only when
            # the concrete args are fully resolved (not themselves type params of an
            # enclosing generic — that call is re-inferred when the OUTER template
            # is instantiated).
            resolved_args = [type_map.get(tp.name) for tp in func_info.type_params]
            if all(a is not None and self._is_concrete_type(a) for a in resolved_args):
                self._effect_record_poly_call(
                    expr.name, resolved_args, f"`{expr.name}`", expr.line)
            param_types = [t.substitute(type_map) for t in func_info.param_types]
            return_type = func_info.return_type.substitute(type_map)
        else:
            if expr.type_args:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{expr.name}` is not generic but was called with type arguments",
                    expr.line, expr.column
                )
            param_types = func_info.param_types
            return_type = func_info.return_type
        # Default parameter values (design 53): an omitted trailing argument is
        # filled at the call site, so a call may provide between `required` and
        # `len(param_types)` arguments.
        dvals = func_info.default_values or []
        has_defaults = any(dv is not None for dv in dvals)
        required = (sum(1 for dv in dvals if dv is None) if has_defaults
                    else len(param_types))
        # Design 66: labeled arguments bind by the binding rule (which also
        # validates arity/missing/too-many); positional-only calls keep the
        # exact legacy arity checks and identity binding.
        has_labels = self._call_has_labels(expr)
        if has_labels and func_info.is_variadic:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"labeled arguments are not supported on variadic function "
                f"`{expr.name}`", expr.line, expr.column)
            return return_type
        if has_labels:
            mapping = self._bind_args(expr, func_info.param_names, dvals, expr.name)
            if mapping is None:
                return return_type
        else:
            mapping = None
            if func_info.is_variadic:
                if len(expr.arguments) < len(param_types):
                    self._error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"function `{expr.name}` takes at least {len(param_types)} argument(s), "
                        f"but {len(expr.arguments)} were given",
                        expr.line, expr.column
                    )
                    return return_type
            elif has_defaults:
                if len(expr.arguments) < required or len(expr.arguments) > len(param_types):
                    self._error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"function `{expr.name}` takes between {required} and "
                        f"{len(param_types)} argument(s), but {len(expr.arguments)} "
                        f"were given",
                        expr.line, expr.column
                    )
                    return return_type
            else:
                if len(expr.arguments) != len(param_types):
                    self._error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"function `{expr.name}` takes {len(param_types)} argument(s), "
                        f"but {len(expr.arguments)} were given",
                        expr.line, expr.column
                    )
                    return return_type
        # Design 108: for a GENERIC call, an OMITTED default-valued parameter must
        # have its default expression fit the INSTANTIATED parameter type. The
        # declaration-time check (design 53) ran against the abstract `T` and was
        # skipped, so this is the only place the default is validated per call —
        # `f<Float>(1)` with `b: T = 0` is a clean anchored error (a bare integer
        # literal does not adopt Float), never a codegen ICE.
        if func_info.type_params:
            self._check_generic_call_defaults(expr, func_info, param_types, mapping)
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] if mapping is not None else i
            expected_type = param_types[p] if p < len(param_types) else None
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type, as_call_argument=True)
            else:
                self._apply_literal_expected_type(arg.value, expected_type)
                arg_type = self._check_expression(arg.value)
            declared = (func_info.param_types[p]
                        if p < len(func_info.param_types) else None)
            allow_wrap = self._df3_allow_wrap(
                declared, {tp.name for tp in (func_info.type_params or [])})
            if self._try_existential_arg_coercion(arg, arg_type, expected_type):
                pass  # `&concrete -> &any Trait` erasure (or its error) handled
            elif arg_type and expected_type is not None and not self._arg_type_ok(
                    arg.value, arg_type, expected_type, allow_wrap):
                param_name = func_info.param_names[p]
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column,
                    hint=self._int_conversion_hint(arg_type, expected_type)
                )
            # Design 87: literal fixed-width adoption + range check ran in the
            # `_apply_literal_expected_type` propagation above — subsumed here.
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        # Variadic extra arguments have no declared parameter type to check
        # against, but must still flow through the chokepoint so codegen sees
        # their resolved_type annotations. (Variadic calls are never labeled.)
        if mapping is None:
            for arg in expr.arguments[len(param_types):]:
                self._check_expression(arg.value)
                self._check_value_transfer(arg.value, None, "call argument",
                                           arg.value.line, arg.value.column)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping, param_types, func_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments], aligned_types,
                                     param_names=aligned_names)
        return return_type

    def _check_if_expr(self, expr: IfExpr) -> Optional[SawType]:
        """Check an if expression."""
        cond_type = self._check_expression(expr.condition)
        if cond_type and cond_type.kind != TypeKind.BOOL:
            if cond_type.kind != TypeKind.INT:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"condition must be `Bool`, got `{cond_type}`",
                    expr.line, expr.column
                )
        # Move dataflow (design 15 rule 6): check both branches from the same
        # entry state, then union-merge, excluding branches that diverge.
        entry_moves = self._snapshot_moves()
        then_type = self._check_block(expr.then_branch)
        then_state = self._snapshot_moves()
        then_diverges = self._block_has_early_exit(expr.then_branch)
        self.moved_bindings = dict(entry_moves)
        else_type = None
        if expr.else_branch:
            else_type = self._check_block(expr.else_branch)
            else_state = self._snapshot_moves()
            else_diverges = self._block_has_early_exit(expr.else_branch)
        else:
            # An absent else contributes the entry state (no new moves).
            else_state = dict(entry_moves)
            else_diverges = False
        self.moved_bindings = self._merge_move_branches(
            entry_moves,
            [(then_state, then_diverges), (else_state, else_diverges)])

        if expr.else_branch:
            # design 49: a diverging branch (`panic(...)`, type NEVER) contributes
            # no value to the merge — the `if` takes the other branch's type.
            if then_type is not None and then_type.kind == TypeKind.NEVER:
                return else_type
            if else_type is not None and else_type.kind == TypeKind.NEVER:
                return then_type
            # design 205: an INTEGER pair is design 195 rule 2's business, not
            # this general test's — `_merge_value_branch_types` below owns both
            # the lossless-widening admission and the refusal, with the three
            # conversion spellings in its hint.
            if (then_type and else_type
                    and not self._both_int_kinds(then_type, else_type)
                    and not self._types_compatible(then_type, else_type)):
                # Check if branches could be Result auto-wrapped.
                # design 213 entry point 2: inside a closure this is the
                # CLOSURE's return type — a closure declared `-> Result<T, E>`
                # gets the same Ok/Err arm reconciliation a named function does.
                expected_return = self._enclosing_return_type()

                if expected_return and expected_return.is_result():
                    ok_type = expected_return.type_args[0] if expected_return.type_args else None
                    err_type = expected_return.type_args[1] if expected_return.type_args and len(expected_return.type_args) > 1 else None

                    # Check if branches match Ok and Err types
                    then_is_ok = ok_type and self._types_compatible(then_type, ok_type)
                    then_is_err = err_type and self._types_compatible(then_type, err_type)
                    else_is_ok = ok_type and self._types_compatible(else_type, ok_type)
                    else_is_err = err_type and self._types_compatible(else_type, err_type)

                    if (then_is_ok or then_is_err) and (else_is_ok or else_is_err):
                        # Wrap branch final expressions in ResultOkWrap/ResultErrWrap
                        if expr.then_branch.final_expr:
                            if then_is_ok:
                                expr.then_branch.final_expr = ResultOkWrap(
                                    value=expr.then_branch.final_expr,
                                    result_type=expected_return,
                                    line=expr.then_branch.final_expr.line,
                                    column=expr.then_branch.final_expr.column
                                )
                            elif then_is_err:
                                expr.then_branch.final_expr = ResultErrWrap(
                                    value=expr.then_branch.final_expr,
                                    result_type=expected_return,
                                    line=expr.then_branch.final_expr.line,
                                    column=expr.then_branch.final_expr.column
                                )
                        if expr.else_branch.final_expr:
                            if else_is_ok:
                                expr.else_branch.final_expr = ResultOkWrap(
                                    value=expr.else_branch.final_expr,
                                    result_type=expected_return,
                                    line=expr.else_branch.final_expr.line,
                                    column=expr.else_branch.final_expr.column
                                )
                            elif else_is_err:
                                expr.else_branch.final_expr = ResultErrWrap(
                                    value=expr.else_branch.final_expr,
                                    result_type=expected_return,
                                    line=expr.else_branch.final_expr.line,
                                    column=expr.else_branch.final_expr.column
                                )
                        return expected_return

                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`if` and `else` branches have incompatible types: `{then_type}` vs `{else_type}`",
                    expr.line, expr.column
                )
            if then_type and else_type:
                if else_type.is_none_literal() and not then_type.is_optional():
                    result_type = then_type.wrap_optional()
                    self._annotate_none_in_block(expr.else_branch, result_type)
                    # Wrap the then branch in OptionalWrap
                    if expr.then_branch.final_expr:
                        expr.then_branch.final_expr = OptionalWrap(
                            value=expr.then_branch.final_expr,
                            target_type=result_type,
                            line=expr.then_branch.final_expr.line,
                            column=expr.then_branch.final_expr.column
                        )
                    return result_type
                if else_type.is_none_literal() and then_type.is_optional():
                    self._annotate_none_in_block(expr.else_branch, then_type)
                    return then_type
                if then_type.is_none_literal() and not else_type.is_optional():
                    result_type = else_type.wrap_optional()
                    self._annotate_none_in_block(expr.then_branch, result_type)
                    # Wrap the else branch in OptionalWrap
                    if expr.else_branch.final_expr:
                        expr.else_branch.final_expr = OptionalWrap(
                            value=expr.else_branch.final_expr,
                            target_type=result_type,
                            line=expr.else_branch.final_expr.line,
                            column=expr.else_branch.final_expr.column
                        )
                    return result_type
                if then_type.is_none_literal() and else_type.is_optional():
                    self._annotate_none_in_block(expr.then_branch, else_type)
                    return else_type
                # Wrap T branch in Optional if other branch is T?
                if else_type.is_optional() and not then_type.is_optional():
                    if expr.then_branch.final_expr:
                        expr.then_branch.final_expr = OptionalWrap(
                            value=expr.then_branch.final_expr,
                            target_type=else_type,
                            line=expr.then_branch.final_expr.line,
                            column=expr.then_branch.final_expr.column
                        )
                    return else_type
                if then_type.is_optional() and not else_type.is_optional():
                    if expr.else_branch.final_expr:
                        expr.else_branch.final_expr = OptionalWrap(
                            value=expr.else_branch.final_expr,
                            target_type=then_type,
                            line=expr.else_branch.final_expr.line,
                            column=expr.else_branch.final_expr.column
                        )
                    return then_type
            # design 195 rule 2: the two branches are TRANSFERS into one merged
            # home, so an arm that widens losslessly is free and one that cannot
            # is the ordinary transfer error. Skipped when the arms were already
            # reported incompatible above — one diagnostic per disagreement.
            #
            # Until this, mismatched-width arms fell past the phi in codegen and
            # the `if` handed back the THEN value on both paths (DF-192g, a
            # confirmed wrong answer).
            if (self._both_int_kinds(then_type, else_type)
                    or self._types_compatible(then_type, else_type)):
                merged = self._merge_value_branch_types(
                    [then_type, else_type],
                    "the `if` and `else` branches", expr.line, expr.column)
                if merged is not None:
                    expr.then_branch.final_expr = self._widened(
                        expr.then_branch.final_expr, merged)
                    expr.else_branch.final_expr = self._widened(
                        expr.else_branch.final_expr, merged)
                    return merged
            return then_type or else_type
        else:
            return then_type

    def _check_if_let_expr(self, expr: IfLetExpr) -> Optional[SawType]:
        """Check an if let/var expression for optional binding.

        THE OPTIONAL-BINDING FUNNEL (obligation 1). Every rule about what an
        optional binding may bind lives here and nowhere else — the design-100
        derived-shadow test, the design-63 tuple pattern, the design-131
        payload-read tier — so a new spelling of the construct gets all of them
        by routing through this method rather than by growing a copy.

        ENTRY POINTS:
          * `parser/expressions.py parse_if_expression` — `if let` / `if var`.
          * `parser/statements.py _parse_while_let` — `while let` / `while var`
            (design 233), which lowers to an `if let` whose synthesized `else`
            is a `break`. `expr.while_let` marks those, and it exists for the
            two things the desugared node can no longer say for itself: a
            diagnostic must name what the author wrote, and the branch-type
            merge must not judge an `else` the author never wrote.
        (`guard let` is checked by `_check_guard_let_statement`, which repeats
        the shape rather than this method's control flow but calls the same
        three helpers.)
        """
        from .core import VariableInfo, Scope
        kw = "while let" if expr.while_let else "if let"
        kw_a = "a `while let`" if expr.while_let else "an `if let`"
        optional_type = self._check_expression(expr.optional_expr)
        if optional_type is None:
            return None
        if optional_type.kind != TypeKind.OPTIONAL:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"'{kw}' requires an optional type, got `{optional_type}`",
                expr.line, expr.column
            )
            return None
        inner_type = optional_type.inner_type
        if inner_type is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot determine type of bound variable from None literal",
                expr.line, expr.column
            )
            return None
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)
        if expr.pattern is not None:
            # Design 100: tuple-pattern bindings BIND (no per-binding derive) —
            # a shadow of an enclosing binding is a flat error.
            for nm, nl, nc in self._pattern_binding_names(expr.pattern):
                self._check_shadowing(nm, None, nl, nc, site="pattern")
            # Tuple pattern over an Optional tuple (design 63).
            self._bind_optional_pattern(expr.pattern, inner_type, expr.mutable,
                                        expr.line, expr.column)
        else:
            # Design 100: `if let x = x` (scrutinee mentions the shadowed
            # enclosing binding) stays legal by the main rule; a non-deriving
            # single-name shadow is an error.
            self._check_shadowing(expr.name, expr.optional_expr,
                                  expr.line, expr.column, site="binding")
            # Design 111 rider: `if let _ = opt` evaluates + tests the Optional but
            # BINDS NOTHING (the payload drops immediately at codegen). This is the
            # idiomatic way to consume a `Void?` (`if let _ = x?.y = v`).
            if expr.name != "_":
                self.current_scope.define(
                    expr.name,
                    VariableInfo(inner_type, expr.mutable, expr.line, expr.column)
                )
                # design 131: the binding is a VALUE READ of the payload. Out of
                # a place the scrutinee keeps, that read follows the copy policy
                # — retain for Copy, refused for ExplicitCopy/NoCopy
                # (`if let a = move o` is the consuming form). A fresh temporary
                # scrutinee already handed its payload over and is unchanged.
                self._check_payload_read(expr.optional_expr, inner_type, expr,
                                         f"{kw_a} binding",
                                         expr.line, expr.column)
        # Move dataflow (design 15 rule 6): branches merge as union of the
        # non-diverging paths, from a shared entry state.
        entry_moves = self._snapshot_moves()
        then_type = self._check_block(expr.then_branch)
        then_state = self._snapshot_moves()
        then_diverges = self._block_has_early_exit(expr.then_branch)
        self.current_scope = old_scope
        self.moved_bindings = dict(entry_moves)
        else_type = None
        if expr.else_branch:
            else_type = self._check_block(expr.else_branch)
            else_state = self._snapshot_moves()
            else_diverges = self._block_has_early_exit(expr.else_branch)
        else:
            else_state = dict(entry_moves)
            else_diverges = False
        self.moved_bindings = self._merge_move_branches(
            entry_moves,
            [(then_state, then_diverges), (else_state, else_diverges)])
        if expr.else_branch:
            # design 49: a diverging branch (`panic(...)`, type NEVER) takes the
            # other branch's type.
            if then_type is not None and then_type.kind == TypeKind.NEVER:
                return else_type
            if else_type is not None and else_type.kind == TypeKind.NEVER:
                return then_type
            if expr.while_let:
                # design 233: the `else` is the synthesized `break` that leaves
                # the loop, not a branch the author wrote — there is no second
                # value to merge with, and a `while let` yields nothing anyway
                # (value position is refused in `_check_while_expr_as_expression`).
                return then_type
            if then_type and else_type and not self._types_compatible(then_type, else_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`if let` branches have incompatible types: `{then_type}` vs `{else_type}`",
                    expr.line, expr.column
                )
            if then_type and else_type:
                if else_type.is_none_literal() and not then_type.is_optional():
                    result_type = then_type.wrap_optional()
                    self._annotate_none_in_block(expr.else_branch, result_type)
                    return result_type
                if else_type.is_none_literal() and then_type.is_optional():
                    self._annotate_none_in_block(expr.else_branch, then_type)
                    return then_type
                if then_type.is_none_literal() and not else_type.is_optional():
                    result_type = else_type.wrap_optional()
                    self._annotate_none_in_block(expr.then_branch, result_type)
                    return result_type
                if then_type.is_none_literal() and else_type.is_optional():
                    self._annotate_none_in_block(expr.then_branch, else_type)
                    return else_type
            return then_type or else_type
        else:
            return then_type

    def _check_tuple_literal(self, expr: TupleLiteral) -> Optional[SawType]:
        """Check a tuple literal (design 63: carries field labels for a named
        tuple literal `(x: 3, y: 4)`).

        DF-151l: when the context DECLARED a tuple type, its element types are
        what the elements are checked against — the same job the array literal's
        `arr_elem` does (DF-151e), through the same `_element_fits` helper, so
        the one-level `T -> T?` auto-wrap is recorded on the element. Without it
        the literal took each element's own type, so an annotated `(Int?, Int)`
        never reached its elements: a bare `None` stayed untyped (`inner_type=
        None`, an ICE at the codegen None literal) and a bare `Int` was stored
        UNWRAPPED, laying the tuple out `{i64, i64}` while the storage and every
        read believed `{{i1,i64}, i64}` — an ICE on the first read.
        """
        expected = getattr(expr, 'expected_type', None)
        declared = None
        if (expected is not None and expected.kind == TypeKind.TUPLE
                and expected.element_types
                and len(expected.element_types) == len(expr.elements)):
            declared = expected.element_types

        element_types = []
        for i, element in enumerate(expr.elements):
            elem_type = self._check_expression(element)
            if elem_type is None:
                return None
            target = declared[i] if declared is not None else elem_type
            if declared is not None and not self._element_fits(element, elem_type,
                                                               target):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"tuple element {i} has type `{elem_type}`, expected "
                    f"`{target}`",
                    element.line, element.column,
                    hint=self._int_conversion_hint(elem_type, target)
                )
                return None
            element_types.append(target)
            self._check_value_transfer(element, target, "tuple element",
                                       element.line, element.column)
        field_names = getattr(expr, 'field_names', None)
        if declared is not None and expected.tuple_field_names:
            # A declared named tuple keeps its labels even when the literal was
            # written positionally (`let p: (x: Int, y: Int) = (1, 2)`).
            field_names = field_names or expected.tuple_field_names
        return SawType(TypeKind.TUPLE, element_types=element_types,
                       tuple_field_names=field_names)

    def _check_tuple_index(self, expr: TupleIndex) -> Optional[SawType]:
        """Check tuple indexing."""
        tuple_type = self._check_expression(expr.tuple_expr)
        if tuple_type is None:
            return None
        if tuple_type.kind != TypeKind.TUPLE:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index into non-tuple type `{tuple_type}`",
                expr.line, expr.column
            )
            return None
        if tuple_type.element_types is None:
            return None
        if expr.index < 0 or expr.index >= len(tuple_type.element_types):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"tuple index {expr.index} out of range for tuple with {len(tuple_type.element_types)} elements",
                expr.line, expr.column
            )
            return None
        return tuple_type.element_types[expr.index]

    def _check_array_literal(self, expr: ArrayLiteral) -> Optional[SawType]:
        """Check an array literal and infer its type.

        Design 54 Part 4: when the EXPECTED type (stamped by a binding
        annotation / parameter / return / struct field) is `Vector<T, A>`, the
        literal builds a Vector (per-element push) instead of a fixed-size
        array. With no expected type it stays a fixed-size array, byte-for-byte
        as before."""
        expected = getattr(expr, 'expected_type', None)
        vec_elem = None
        arr_elem = None
        if (expected is not None and expected.kind == TypeKind.STRUCT
                and expected.struct_name == "Vector" and expected.type_args):
            vec_elem = expected.type_args[0]
        elif (expected is not None and expected.kind == TypeKind.ARRAY
                and expected.array_element_type is not None):
            # The ANNOTATED element type is the one the elements are checked
            # against — the same job `vec_elem` does for a Vector (DF-151e).
            # Without it the literal took its element type from element 0 alone,
            # so `[T?; N]` never reached its elements: a `None` stayed untyped
            # (`inner_type=None`, an ICE at the codegen None literal) and a bare
            # `T` was stored UNWRAPPED, laying the value out `[T x N]` while the
            # storage, the element drop and every read believed `[{i1,T} x N]`.
            arr_elem = expected.array_element_type

        if expr.repeat_count is not None:
            return self._check_repeat_literal(expr, vec_elem, expected, arr_elem)

        if len(expr.elements) == 0:
            if vec_elem is not None:
                # Empty Vector via context: `let v: Vector<Int> = []`.
                expr.vector_container_type = expected
                return expected
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "cannot infer type of empty array literal; use explicit type annotation",
                expr.line, expr.column
            )
            return None

        # Element unification target: the DECLARED element type when the context
        # named one (a Vector's `T`, or a fixed array's), otherwise inferred from
        # the first element.
        declared_elem = vec_elem if vec_elem is not None else arr_elem
        first_type = self._check_expression(expr.elements[0])
        if first_type is None:
            return None
        target = declared_elem if declared_elem is not None else first_type
        if vec_elem is not None and not self._element_fits(expr.elements[0],
                                                           first_type, vec_elem):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"vector literal element 0 has type `{first_type}`, expected `{vec_elem}`",
                expr.elements[0].line, expr.elements[0].column,
                hint=self._int_conversion_hint(first_type, vec_elem))
            return None
        if arr_elem is not None and not self._element_fits(expr.elements[0],
                                                           first_type, arr_elem):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"array element 0 has type `{first_type}`, expected `{arr_elem}`",
                expr.elements[0].line, expr.elements[0].column,
                hint=self._int_conversion_hint(first_type, arr_elem))
            return None
        self._check_value_transfer(expr.elements[0], target, "array element",
                                   expr.elements[0].line, expr.elements[0].column)
        for i, element in enumerate(expr.elements[1:], start=1):
            elem_type = self._check_expression(element)
            if elem_type is None:
                return None
            if not self._element_fits(element, elem_type, target):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"array element {i} has type `{elem_type}`, expected `{target}`",
                    element.line, element.column,
                    hint=self._int_conversion_hint(elem_type, target)
                )
                return None
            self._check_value_transfer(element, target, "array element",
                                       element.line, element.column)
        if vec_elem is not None:
            expr.vector_container_type = expected
            return expected
        return SawType(TypeKind.ARRAY, array_element_type=target,
                       array_size=len(expr.elements))

    def _element_fits(self, element, elem_type, target) -> bool:
        """Whether a collection-literal element of `elem_type` may occupy a
        `target` slot, recording the one-level `T -> T?` auto-wrap on the element
        when that is what makes it fit (DF-151e).

        An element position is a transfer into a declared slot, exactly like a
        call argument or a struct-literal field, so it gets the same rule: a bare
        `None` takes the slot's payload type and a bare `T` records the wrap that
        codegen builds `Some(x)` from. `target` is the element's own type when
        nothing declared one, in which case there is nothing to wrap and this is
        the plain compatibility test it always was.

        DF-218f: `Result` is a slot type here for the same reason, so the
        funnel is asked about it too — `let rs: Vector<Result<Int, E>> = [9]`
        had no working spelling before, since Saw writes no `Ok(9)`.
        """
        if target is not None and (target.is_optional() or target.is_result()):
            return self._arg_type_ok(element, elem_type, target)
        return self._transfer_compatible(elem_type, target)

    def _check_repeat_literal(self, expr: ArrayLiteral, vec_elem, expected,
                              arr_elem=None):
        """Check a repeat literal `[v; N]` — N copies of one value (design 148).

        `[0; 256]` is what finally spells a zero stack buffer; before it, the
        only way to write one was 256 literal zeros, which is why the panic
        scratch buffer had to be allocated by the compiler rather than in Saw
        (DF-137b).
        """
        # A repeat literal is a FIXED array. `let v: Vector<Int> = [0; 8]` would
        # have to mean "a Vector of 8 zeros", which is `Vector` construction and
        # not a literal at all — refusing it by name beats silently building an
        # 8-element fixed array where a Vector was annotated.
        if vec_elem is not None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"a repeat literal `[v; N]` builds a fixed array, not a "
                f"`{expected}`",
                expr.line, expr.column,
                hint="drop the annotation to get `[T; N]`, or build the vector "
                     "with a loop of `push`")
            return None

        value = expr.elements[0]
        elem_type = self._check_expression(value)
        if elem_type is None:
            return None
        if arr_elem is not None:
            # The annotated element type wins, so `[None; 4]` and `[7; 4]` both
            # reach an `[Int?; 4]` slot: the first gets its payload type, the
            # second records the `T -> T?` wrap (DF-151e). The copy-tier check
            # below then asks about `T?`, which design 139 says carries `T`'s
            # tier — so a `[v; 3]` of a Vector is refused whether or not the
            # annotation wrapped it in an optional.
            if not self._element_fits(value, elem_type, arr_elem):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"array element 0 has type `{elem_type}`, expected "
                    f"`{arr_elem}`",
                    value.line, value.column)
                return None
            elem_type = arr_elem

        count = self._const_count(expr.repeat_count, "repeat count")
        if count is None:
            return None
        if count is _ABSTRACT_COUNT:
            # A `[v; N]` inside a generic body: constant, but its value belongs
            # to the instantiation. The length rides along as an expression and
            # every instantiation folds its own. The copy-policy check below
            # still applies — the body has to be correct for every N.
            if not (self._is_trivially_copyable(elem_type)
                    or self._is_implicit_copy_type(elem_type)):
                count = 2       # force the refusal below to fire
            else:
                self._check_value_transfer(value, elem_type, "array element",
                                           value.line, value.column)
                return SawType(TypeKind.ARRAY, array_element_type=elem_type,
                               array_size_expr=expr.repeat_count)
        if count < 0:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"repeat count is negative (`{count}`)",
                expr.repeat_count.line, expr.repeat_count.column,
                hint="an array length counts elements, so it starts at 0")
            return None

        # Every copy is a copy. A trivially-copyable element is duplicated
        # bitwise and a Copy one retains N times, both of which the
        # value's own transfer checkpoint below accounts for. An ExplicitCopy or
        # NoCopy element cannot be: `move v` transfers ONE value and there is no
        # spelling for "and N-1 more", so the literal is refused by name rather
        # than quietly aliasing the same buffer N times.
        # "Copies are free" is a question about the TIER, so it goes to design
        # 139's oracle rather than to a conformance lookup (design 159). The
        # conformance-based predicate could not see the UNDECLARED Copy
        # tier, so `[p; 3]` on a `struct P { name: String }` was refused with a
        # diagnostic that called `P` ExplicitCopy — a policy it does not have
        # and could not be given, since such a struct is exempt from declaring
        # one at all.
        if count > 1 and self.namespace.copy_tier(elem_type) not in ('free',
                                                                    'implicit'):
            if self._is_abstract_type_param(elem_type):
                # An opaque type parameter has no copy policy — it has whatever
                # its instantiation brings, and no bound expresses "copies are
                # BITWISE free", which is what a repeat literal wants: `Copy`
                # admits the retain family, whose N-fold repeat is N retains
                # rather than one memcpy. So the element type is
                # concrete in v1 (DF-148a), and the message says that rather
                # than naming a policy the parameter does not have.
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"a repeat literal needs an element type whose copies are "
                    f"free, and the type parameter `{elem_type}` is not known "
                    f"to be one",
                    value.line, value.column,
                    hint="v1 repeats a CONCRETE element (`[0; N]`, `[\"\"; N]`) "
                         "— no bound yet says `T` copies for free, so a generic "
                         "element cannot be repeated")
                return None
            if self._is_no_copy_type(elem_type):
                policy, hint = "NoCopy", (
                    "a NoCopy value has exactly one owner, so there is nothing "
                    "to repeat — build the array element by element, moving a "
                    "separate value into each slot")
            else:
                policy, hint = "ExplicitCopy", (
                    "an ExplicitCopy value duplicates only where you write "
                    "`.copy()` — build the array element by element so each "
                    "copy is spelled out")
            self._error(
                ErrorKind.CANNOT_COPY,
                f"a repeat literal needs a freely copyable element, and "
                f"`{elem_type}` is {policy}",
                value.line, value.column, hint=hint)
            return None

        self._check_value_transfer(value, elem_type, "array element",
                                   value.line, value.column)
        return SawType(TypeKind.ARRAY, array_element_type=elem_type,
                       array_size=count)

    def _const_count(self, expr, what: str):
        """Evaluate a compile-time count/length.

        Returns the integer, `_ABSTRACT_COUNT` for an expression that IS
        constant but whose value belongs to an instantiation (`[v; N]` inside a
        generic body), or None having reported why it is not constant at all.

        The one evaluator (`const_eval.py`) answers here, in `static_assert`,
        and in an array length, so the three can never disagree about what a
        constant is. The typechecker passes no layout oracle — it knows the word
        width but not struct layout — so `sizeof<T>()` in a length is rejected
        by name here and folded later, in codegen, where the layout exists.
        """
        # Type-check it first: that surfaces an ordinary type error in the
        # count (and stamps the `Int.max` annotation the evaluator reads)
        # before the constant question is asked. In a CONST position (design 185
        # unit 3), which is what this is.
        with self._const_position():
            if self._check_expression(expr) is None:
                return None
        # Const parameters in scope are constants with no value here — a generic
        # body is checked once, abstractly, and the values arrive per
        # instantiation. Probing with a stand-in separates "not a constant" from
        # "a constant this pass cannot see", which are different answers.
        probe = dict.fromkeys(self._const_param_types().keys(), 1)
        probe.update(self._const_param_env())
        # DF-172j: bind the module statics the count names, so `[0; REGION_SIZE]`
        # folds beside the `[UInt8; REGION_SIZE]` it fills.
        self._stamp_const_names(expr)
        try:
            value = const_eval(expr, env=probe, width=self.platform_int_width)
        except ConstEvalError as e:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"{what} is not a compile-time constant: {e.what} is not "
                f"allowed here",
                e.line or expr.line, e.column or expr.column,
                hint=CONST_LENGTH_HINT)
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"{what} must be an integer",
                expr.line, expr.column)
            return None
        if self._mentions_const_param(expr):
            return _ABSTRACT_COUNT
        return value

    def _is_abstract_type_param(self, t) -> bool:
        """Whether `t` is an in-scope generic type parameter rather than a
        concrete type — a name the parser left as STRUCT, or a TYPE_PARAM."""
        if t is None:
            return False
        if t.kind == TypeKind.TYPE_PARAM:
            return True
        params = getattr(self, 'current_type_params', None) or {}
        return t.kind == TypeKind.STRUCT and t.struct_name in params

    def _mentions_const_param(self, expr) -> bool:
        """Whether a constant expression reads a const generic parameter."""
        names = self._const_param_types()
        if not names:
            return False
        from ast_nodes import Identifier as _Id, UnaryOp as _U, BinaryOp as _B
        if isinstance(expr, _Id):
            return expr.name in names
        if isinstance(expr, _U):
            return self._mentions_const_param(expr.operand)
        if isinstance(expr, _B):
            return (self._mentions_const_param(expr.left)
                    or self._mentions_const_param(expr.right))
        return False

    def _const_param_env(self):
        """The const generic parameters in scope, as name -> VALUE.

        Always empty in the typechecker: a generic body is checked once,
        abstractly, so no instantiation's values are in force. Codegen has the
        twin that is populated (design 148). The method exists so every constant
        position asks the same question in the same way.
        """
        return getattr(self, 'current_const_params', None) or {}

    def _const_param_types(self):
        """The const generic parameters in scope, as name -> declared type."""
        return getattr(self, 'current_const_param_types', None) or {}

    def _check_map_literal(self, expr: MapLiteral) -> Optional[SawType]:
        """Check a map literal `{k: v, ...}` / `{:}` (design 54 Part 3).

        K/V are inferred from the entries, or taken from an expected
        `Map<K, V, A>` type (annotation/param/return/field) which also allows a
        custom allocator. `{:}` requires an expected type."""
        expected = getattr(expr, 'expected_type', None)
        exp_map = (expected if (expected is not None and expected.kind == TypeKind.STRUCT
                                and expected.struct_name == "Map") else None)
        if expected is not None and exp_map is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"a map literal cannot initialize a value of type `{expected}`",
                expr.line, expr.column)
            return None

        exp_k = exp_map.type_args[0] if (exp_map and len(exp_map.type_args) >= 1) else None
        exp_v = exp_map.type_args[1] if (exp_map and len(exp_map.type_args) >= 2) else None

        if len(expr.entries) == 0:
            # `{:}` — the empty map needs an expected type to fix K/V.
            if exp_map is None:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "cannot infer the type of the empty map literal `{:}`; "
                    "add a type annotation (e.g. `let m: Map<String, Int> = {:}`)",
                    expr.line, expr.column)
                return None
            self._check_map_key_bounds(exp_k, expr)
            expr.resolved_type = exp_map
            return exp_map

        key_type = exp_k
        val_type = exp_v
        for i, (k_expr, v_expr) in enumerate(expr.entries):
            kt = self._check_expression(k_expr)
            vt = self._check_expression(v_expr)
            if kt is None or vt is None:
                return None
            if key_type is None:
                key_type = kt
            elif not self._transfer_compatible(kt, key_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"map key {i} has type `{kt}`, expected `{key_type}` "
                    f"(all keys in a map literal must share one type)",
                    k_expr.line, k_expr.column,
                    hint=self._int_conversion_hint(kt, key_type))
                return None
            if val_type is None:
                val_type = vt
            elif not self._transfer_compatible(vt, val_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"map value {i} has type `{vt}`, expected `{val_type}` "
                    f"(all values in a map literal must share one type)",
                    v_expr.line, v_expr.column,
                    hint=self._int_conversion_hint(vt, val_type))
                return None

        self._check_map_key_bounds(key_type, expr)
        container = exp_map if exp_map is not None else SawType(
            TypeKind.STRUCT, struct_name="Map", type_args=[key_type, val_type])
        # Each entry is consumed exactly as an `insert(k, v)` argument would be
        # (moves for owning values); the checkpoint sees N independent transfers.
        eff_k = exp_k if exp_k is not None else key_type
        eff_v = exp_v if exp_v is not None else val_type
        for (k_expr, v_expr) in expr.entries:
            self._check_value_transfer(k_expr, eff_k, "map key",
                                       k_expr.line, k_expr.column)
            self._check_value_transfer(v_expr, eff_v, "map value",
                                       v_expr.line, v_expr.column)
        expr.resolved_type = container
        return container

    def _check_set_literal(self, expr: SetLiteral) -> Optional[SawType]:
        """Check a set literal `{a, b, ...}` (design 54 Part 3)."""
        expected = getattr(expr, 'expected_type', None)
        exp_set = (expected if (expected is not None and expected.kind == TypeKind.STRUCT
                                and expected.struct_name == "Set") else None)
        if expected is not None and exp_set is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"a set literal cannot initialize a value of type `{expected}`",
                expr.line, expr.column)
            return None
        exp_t = exp_set.type_args[0] if (exp_set and len(exp_set.type_args) >= 1) else None

        elem_type = exp_t
        for i, e_expr in enumerate(expr.elements):
            et = self._check_expression(e_expr)
            if et is None:
                return None
            if elem_type is None:
                elem_type = et
            elif not self._transfer_compatible(et, elem_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"set element {i} has type `{et}`, expected `{elem_type}` "
                    f"(all elements in a set literal must share one type)",
                    e_expr.line, e_expr.column,
                    hint=self._int_conversion_hint(et, elem_type))
                return None

        self._check_map_key_bounds(elem_type, expr, what="set element")

        container = exp_set if exp_set is not None else SawType(
            TypeKind.STRUCT, struct_name="Set", type_args=[elem_type])
        eff_t = exp_t if exp_t is not None else elem_type
        for e_expr in expr.elements:
            self._check_value_transfer(e_expr, eff_t, "set element",
                                       e_expr.line, e_expr.column)
        expr.resolved_type = container
        return container

    def _apply_literal_expected_type(self, value_expr, expected_type):
        """Central expected-type propagation for literals (designs 54 + 87).

        Pushes a resolved expected type down onto a literal-bearing subexpression
        BEFORE it is checked. Two jobs, one recursive pass:

        - COLLECTION shaping (design 54): a Map/Set/Vector expectation lets an
          array/map/set literal pick K/V/T, honor a custom allocator, or build a
          Vector rather than a fixed array.
        - FIXED-WIDTH INT adoption (design 87): a bare integer literal flowing
          into a fixed-width int slot (`Int8`..`UInt64`) adopts that type and is
          range-checked AT the literal (in `visit_IntLiteral`) — uniformly, at
          every slot that calls this (let/param/field/return/compound-assign/…),
          THROUGH the "transparent" constructs that forward a value unchanged:
          unary minus, if/match/block arm results, and array/tuple/map/set
          element positions.

        A NON-INTEGER expectation leaves a literal alone. A platform `Int`/`UInt`
        one is adopted like any other since design 205 — the pass has stamped an
        INT/UINT target width since DF-137d, and `visit_IntLiteral` now honours
        it, so `var acc: UInt = 0` types its literal `UInt` rather than leaving
        an `Int` for the (now closed) platform-pair permission to absorb. A
        literal reached by NO integer expectation is still platform `Int`, which
        is the load-bearing invariant: `let x = 5` is unchanged.
        """
        if expected_type is None or value_expr is None:
            return
        rt = self._resolve_type(expected_type)
        if rt is None:
            return
        # design 205: a `type` ALIAS names the same storage its underlying does,
        # so a slot declared with one shapes a literal exactly as the underlying
        # would. `_resolve_type` keeps the alias, so none of the arms below ever
        # matched one: `static ARENA: Region = [0; 8]` for a
        # `type Region = [UInt8; 8]` left the repeat literal's element at
        # platform `Int`, and `let x: Small = 5` for a `type Small = Int8` left
        # the literal at `Int`. Both were absorbed by the platform-pair
        # permission `_types_compatible` used to grant; with it closed they are
        # real mismatches, and the fix is to stamp the expectation the author
        # actually wrote. The alias stays a DISTINCT type everywhere else — this
        # decides a literal's WIDTH, not what flows into what. Only the OUTERMOST
        # name is peeled (`_unalias_top`): a `Vector<Handle>` for a
        # `type Handle = Int` must keep its argument, or the empty literal built
        # against it stops matching the field that asked for it.
        rt = self._unalias_top(rt)

        # (0) Bare `None` → adopt an OPTIONAL expectation (DF-146l). A None
        #     literal has no type of its own, and every slot that pins one used
        #     to do it by hand (`let`/`return`/field/`var` assignment), so the
        #     slots reached only through this recursion — a Map literal VALUE, a
        #     Vector/array/Set element, a tuple element — left the literal
        #     untyped and it reached codegen as an ICE. Doing it here fixes each
        #     of them once, at the point that already knows the expected type.
        #     Stamped as `expected_type` rather than `resolved_type`, exactly as
        #     the integer case below is: this runs BEFORE the literal is checked,
        #     and `_check_expression`'s own stamp would overwrite a `resolved_type`
        #     written here ("later contextual annotation wins").
        if isinstance(value_expr, NoneLiteral):
            if rt.kind == TypeKind.OPTIONAL and rt.inner_type is not None:
                value_expr.expected_type = rt
            return

        # (0b) design 226: a `FuncPointer<F>`-EXPECTED position. The two
        #      construction forms — a zero-capture closure literal and a named
        #      function — are both spelled as an expression that means something
        #      else on its own, so both need the expectation pushed down BEFORE
        #      they are checked, and this is the one propagation every position
        #      already calls. That is what makes the coercion's position matrix
        #      the SAME five rows as every literal's: an argument, an annotated
        #      `let`, a struct field initializer, a `return`, a `static`
        #      initializer. `_check_closure` and `_check_identifier` read the
        #      stamp; nothing else in the language reads a FuncPointer
        #      expectation, so no existing meaning changes.
        if (isinstance(value_expr, (ClosureExpr, Identifier))
                and self._funcpointer_signature(rt) is not None):
            value_expr.expected_type = rt
            return

        # (0c) An OPTIONAL expectation over a value the slot will AUTO-WRAP: the
        #      literal underneath owes the PAYLOAD's type, not the optional's.
        #      `let x: Int32? = 1` is the shape — the wrap is inserted for us, so
        #      what the author wrote is an `Int32`, and leaving the literal at
        #      platform `Int` built a `{i1, i64}` where a `{i1, i32}` was owed.
        #      That was an internal compiler error at EVERY position the funnel
        #      serves (an annotated `let`, a call argument, a struct field, a
        #      return — tail and `return` alike, in a named body and a closure
        #      body — an array/Vector element), which is what makes this the
        #      funnel's own gap rather than a gap at one of its callers, and what
        #      makes ONE peel here the whole fix.
        #
        #      Peeled only for the LITERAL SHAPES that wrap. A branching
        #      construct keeps the optional expectation, because an arm of it may
        #      be a bare `None` that still has to learn what it is a `None` of
        #      (`if c { 1 } else { None }` at `-> Int32?`) — case (3) recurses
        #      with the optional intact and each arm meets this rule on its own.
        #      A `Result` payload is peeled by case (0d) below, which has to
        #      answer "which payload" before it can peel.
        #
        #      A `BinaryOp` is on the peel list for the same reason (DF-235b): a
        #      constant expression wrapping into an optional slot owes the
        #      PAYLOAD's width too, and case (2b) below is what gives it one.
        #      Peeling one that does not fold costs nothing — (2b) declines and
        #      the expression is checked exactly as it was before.
        if (rt.kind == TypeKind.OPTIONAL and rt.inner_type is not None
                and (isinstance(value_expr, (IntLiteral, TupleLiteral,
                                             ArrayLiteral, MapLiteral,
                                             SetLiteral, BinaryOp))
                     or (isinstance(value_expr, UnaryOp)
                         and value_expr.op == '-'))):
            self._apply_literal_expected_type(value_expr, rt.inner_type)
            return

        # (0d) A `RESULT` expectation over an integer literal the slot will
        #      AUTO-WRAP (DF-226e, ruled Aug 17). Case (0c)'s optional peel is
        #      unambiguous because an optional has exactly ONE payload; a
        #      `Result` has TWO, so this peel must first say which.
        #
        #      THE RULE: peel to the UNIQUE payload that could adopt an integer
        #      literal. `Result<Int32, Bad>` peels to `Int32` (only the Ok side
        #      is an integer) and `Result<String, Int32>` peels to `Int32` on
        #      the ERR side — the auto-wrap that follows picks `Ok`/`Err` by
        #      testing the value's type against each payload, so peeling to the
        #      one payload that CAN take the literal also selects the only
        #      variant it could have meant. Where BOTH payloads could adopt it
        #      (`Result<Int32, Int8>`) nothing is peeled: that is a real
        #      ambiguity, and `_result_autowrap_ambiguous` — which already owns
        #      the `T == E` refusal and now words this case too — demands the
        #      explicit `Result<T, E>.Ok(value:)` / `.Err(error:)`, inside which
        #      the literal has exactly one slot and adopts through case (1).
        #      Where NEITHER could, nothing is peeled and the ordinary type
        #      mismatch reports.
        #
        #      Before this, `return 4` at `-> Result<Int32, E>` left the literal
        #      at platform width and the wrap built an `{i64}` where an `{i32}`
        #      was owed — a `ResultOkWrap`/`ResultErrWrap` codegen ICE, in named
        #      and closure bodies alike, since both reach this funnel.
        #
        #      A `BinaryOp` peels on the same terms (DF-235a): `return
        #      (1 << 3) | (1 << 4)` at `-> Result<UInt16, Bad>` is the same
        #      un-adopted platform-`Int` value, and it was the same
        #      `ResultOkWrap` codegen ICE. "Which payload" is answered the same
        #      way, by the payload that could take an integer.
        if (rt.is_result()
                and (isinstance(value_expr, (IntLiteral, BinaryOp))
                     or (isinstance(value_expr, UnaryOp)
                         and value_expr.op == '-'))):
            adopting = [p for p in (rt.unwrap_result_ok(),
                                    rt.unwrap_result_err())
                        if self._payload_adopts_int_literal(p)]
            if len(adopting) == 1:
                self._apply_literal_expected_type(value_expr, adopting[0])
            return

        # (1) Bare integer literal → adopt a fixed-width expectation, range-check
        #     it AT the literal, and stamp the fixed-width type. Stamping here (not
        #     only via visit_IntLiteral) covers the POST-HOC sites — overloaded
        #     call args are checked before the winning param type is known, then
        #     coerced through this method — as well as the before-check slots.
        if isinstance(value_expr, IntLiteral):
            _rng = (self._int_range_for(rt.kind)
                    if getattr(value_expr, 'suffix', None) is None else None)
            if _rng is not None:
                value_expr.expected_type = rt
                lo, hi = _rng
                if not (lo <= value_expr.value <= hi):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"integer literal {value_expr.value} does not fit in "
                        f"`{expected_type}` (range {lo}..={hi})",
                        getattr(value_expr, 'line', 0),
                        getattr(value_expr, 'column', 0))
                value_expr.resolved_type = SawType(rt.kind)
            return

        # (2) Unary minus of a literal: the fixed-width expectation carries
        #     through to the operand (`let x: Int8 = -5`). The range check runs on
        #     the FOLDED (negated) value — a bare magnitude like Int32.min's
        #     2147483648 is in range only once negated (design 77 item 8) — so it
        #     is handled here rather than via the plain-literal recursion.
        if isinstance(value_expr, UnaryOp) and value_expr.op == '-':
            operand = value_expr.operand
            _rng = (self._int_range_for(rt.kind)
                    if (isinstance(operand, IntLiteral)
                        and getattr(operand, 'suffix', None) is None) else None)
            if _rng is not None:
                operand.expected_type = rt
                lo, hi = _rng
                if not (lo <= -operand.value <= hi):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"integer literal -{operand.value} does not fit in "
                        f"`{expected_type}` (range {lo}..={hi})",
                        getattr(operand, 'line', 0), getattr(operand, 'column', 0))
                operand.resolved_type = SawType(rt.kind)
                return
            # DF-235b: not a bare literal underneath. A NEGATED constant
            # expression (`-(1 << 7)` at `Int8`) has to be folded WHOLE, or the
            # range check would see the magnitude and refuse a value that fits
            # once negated — the very thing the literal arm above exists to get
            # right. Case (2b)'s helper does it; if the operand is not constant
            # it declines and the old recursion runs, unchanged.
            #
            # An ALREADY-folded expression stops here rather than recursing: the
            # front half runs twice over one AST (the place lowering unchecks
            # between them), and descending into the operand on the second pass
            # would range-check the magnitude under the `-` — refusing `Int8.min`
            # written as `-(1 << 7)` on a program that compiled on pass one.
            if value_expr.const_folded_value is not None:
                return
            if (self._const_adoption_slot(rt)
                    and self._fold_const_expression_into(
                        value_expr, rt, expected_type)):
                return
            self._apply_literal_expected_type(operand, rt)
            return

        # (2b) A CONSTANT EXPRESSION — a `BinaryOp` over compile-time-known
        #      operands (`2 + 3`, `1 << 20`, `(1 << 3) | (1 << 4)`) — reaching a
        #      FIXED-WIDTH slot. DF-235a/b: this case did not exist, so a folded
        #      shift or mask matched none of the node shapes above, was checked
        #      with no expectation at all, and came out at platform `Int` —
        #      which every position then dealt with on its own terms. Most
        #      narrowed it at the store with NO range check (`let e: UInt16 =
        #      1 << 20` printed 0), some carried the platform width right past
        #      the declared one (`[1 << 20; 2]` at `[UInt16; 2]`), two crashed
        #      codegen (a mixed array literal, a `Result` payload slot), and
        #      compound assignment's RHS was refused outright by design 195's
        #      operand agreement — five behaviours for one gap.
        #
        #      THE FIX IS THE FUNNEL'S, not each position's: fold it here (the
        #      one `const_eval`, so nothing new can disagree about what a
        #      constant is) and then run the SAME range check case (1) runs on a
        #      bare literal, at the same place, with the same words. Codegen
        #      reads `const_folded_value` and emits the constant AT the stamped
        #      type, so the declared width is the width stored.
        #
        #      SCOPE, deliberately drawn:
        #      - EVERY integer target, since design 257 §1 — see
        #        `_const_adoption_slot` for why the platform pair belongs and
        #        what stayed out. It was fixed widths only until then, on the
        #        reasoning that a platform expectation is what the expression
        #        already had; true of `Int`, false of `UInt`, and DF-282a is
        #        the `UInt` half.
        #      - Whatever `const_eval` answers from the AST it is handed. A
        #        `BinaryOp` naming a module `static` or a raw-backed enum case
        #        folds only where an earlier pass stamped its value, so a runtime
        #        `n * 2` is untouched (const_eval rejects it and we fall through)
        #        and design 185 unit 4's rule that `Perm.Read | Perm.Write` is a
        #        constant only IN a const position is not widened here.
        #      - The fold is design 185's: the signed platform-`Int` domain. So
        #        `1 << 63` is `Int.min` and is refused at a `UInt64` slot, which
        #        is exactly what `(1 << 63) as UInt64` already says and what a
        #        bare `-9223372036854775808` in the same slot already says.
        #      - `~mask` rides here too (`UnaryOp` with `~`); a leading `-` is
        #        case (2)'s, which folds through the same helper. A LONE
        #        raw-backed enum case rides here since design 257 §2 — see
        #        `_const_adoption_shape`.
        #
        #      A SHIFT that does NOT fold forwards its LEFT operand's type: the
        #      count is exempt from operand agreement (design 195) and
        #      contributes nothing to the result, so an expected type reaches
        #      the SHIFTEE exactly as it reaches a unary minus's operand.
        #      `reg.write(1 << n)` for a runtime `n` is that shape — not a
        #      constant, nothing folds, and without the forward the `1` stays
        #      platform `Int` and the write is refused. That was a separate arm
        #      (2c) carrying the platform targets while this one carried the
        #      fixed widths; design 257 §1 gave this arm every integer slot, so
        #      the two are one and the miss path below IS (2c).
        if (self._const_adoption_shape(value_expr)
                and self._const_adoption_slot(rt)):
            if value_expr.const_folded_value is None:
                if not self._fold_const_expression_into(value_expr, rt,
                                                        expected_type):
                    self._apply_shift_expected_type(value_expr, rt)
            return

        # (3) if / match / block whose arm results merge to the expected type.
        if isinstance(value_expr, IfExpr):
            self._apply_literal_expected_type(
                getattr(value_expr.then_branch, 'final_expr', None), rt)
            if value_expr.else_branch is not None:
                self._apply_literal_expected_type(
                    getattr(value_expr.else_branch, 'final_expr', None), rt)
            return
        if isinstance(value_expr, MatchExpr):
            for arm in value_expr.arms:
                self._apply_literal_expected_type(arm.body, rt)
            return
        if isinstance(value_expr, Block):
            self._apply_literal_expected_type(
                getattr(value_expr, 'final_expr', None), rt)
            return

        # (4) Tuple literal into a tuple type: element-wise. Keep the tuple
        #     expectation on the literal, not only its element types —
        #     `_check_tuple_literal` reads it to check each element against the
        #     DECLARED element type rather than taking the element's own
        #     (DF-151l). This is the same stamp the ARRAY branch below makes,
        #     and what makes nesting work: a `((Int?, Int), Int)` annotation
        #     reaches the inner literal through this recursion.
        if isinstance(value_expr, TupleLiteral) and rt.kind == TypeKind.TUPLE:
            value_expr.expected_type = rt
            elem_types = rt.element_types or []
            if len(elem_types) == len(value_expr.elements):
                for e, et in zip(value_expr.elements, elem_types):
                    self._apply_literal_expected_type(e, et)
            return

        # (5) Array literal into `[IntN; M]` or `Vector<IntN, A>`: propagate the
        #     element type (and, for a Vector, keep the collection expectation).
        if isinstance(value_expr, ArrayLiteral):
            elem_t = None
            if rt.kind == TypeKind.ARRAY:
                # Keep the array expectation on the literal, not just its
                # element type: `_check_array_literal` reads it to check the
                # elements against the DECLARED element type rather than
                # inferring one from element 0 (DF-151e). Stamping it here is
                # what makes nesting work — a `[[Int?; 2]; 2]` annotation
                # reaches the inner literals through this same recursion.
                value_expr.expected_type = rt
                elem_t = rt.array_element_type
            elif (rt.kind == TypeKind.STRUCT and rt.struct_name == "Vector"
                    and rt.type_args):
                value_expr.expected_type = rt
                elem_t = rt.type_args[0]
            if elem_t is not None:
                for e in value_expr.elements:
                    self._apply_literal_expected_type(e, elem_t)
            return

        # (6) Map / Set literal: keep the collection expectation (design 54) and
        #     push K/V/T down to element literals (design 87).
        if isinstance(value_expr, MapLiteral):
            if rt.kind == TypeKind.STRUCT:
                value_expr.expected_type = rt
                if rt.struct_name == "Map" and len(rt.type_args) >= 2:
                    for (k_expr, v_expr) in value_expr.entries:
                        self._apply_literal_expected_type(k_expr, rt.type_args[0])
                        self._apply_literal_expected_type(v_expr, rt.type_args[1])
            return
        if isinstance(value_expr, SetLiteral):
            if rt.kind == TypeKind.STRUCT:
                value_expr.expected_type = rt
                if rt.struct_name == "Set" and rt.type_args:
                    for e in value_expr.elements:
                        self._apply_literal_expected_type(e, rt.type_args[0])
            return

    def _key_copyable_reason(self, key_type):
        """Return None if `key_type` may be a Map/Set KEY, else a short reason it
        cannot (design 65 followup, L19). A key is probed by COPY (hash / compare
        / slot inspection), so it must be copyable-with-retain in a balanced way:
        a trivial/POD type (bitwise, no deinit), a Copy type (refcount
        bump), or an ExplicitCopy type (deep copy + symmetric deinit) all balance.
        A NoCopy type, or a `Deinit` type with no copy conformance (move-only,
        no refcount to retain), cannot — its probe copies would run the deinit and
        miscount / double-free. VALUES are unaffected (never probe-copied)."""
        if key_type is None:
            return None
        # An opaque generic type parameter is not concretely known here; the
        # concrete instantiation is checked at the user's call site.
        if (key_type.kind == TypeKind.STRUCT
                and key_type.struct_name in (getattr(self, 'current_type_params', {}) or {})):
            return None
        if (self._is_trivially_copyable(key_type)
                or self._is_implicit_copy_type(key_type)
                or self._is_explicit_copy_type(key_type)):
            return None
        if self._is_no_copy_type(key_type):
            return "is NoCopy"
        return "owns a Deinit without a copy (it is move-only, not retainable)"

    def _check_map_key_copyable(self, key_type, expr, what="map key"):
        reason = self._key_copyable_reason(key_type)
        if reason is not None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"{what} type `{key_type}` must be copyable (trivial, Copy, "
                f"or ExplicitCopy with retain semantics): `{key_type}` {reason}",
                expr.line, expr.column)

    def _check_map_key_bounds(self, key_type, expr, what="map key"):
        """A map key / set element type must be Hashable + Equatable (design
        54, same bound as constructing the container) AND copyable-with-retain
        (design 65 followup: the container probes keys by copy)."""
        if key_type is None:
            return
        for bound in ("Hashable", "Equatable"):
            if not self._bound_satisfied(key_type, bound):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"{what} type `{key_type}` must be `{bound}` "
                    f"(map keys and set elements require Hashable + Equatable)",
                    expr.line, expr.column)
                return
        self._check_map_key_copyable(key_type, expr, what)

    def _check_array_index(self, expr: ArrayIndex) -> Optional[SawType]:
        """Check array or tuple indexing with [index] syntax."""
        container_type = self._check_expression(expr.array_expr)
        if container_type is None:
            return None
        # design 46: index projection through a `UnsafeMemory<[E; N], Use>`
        # region yields `UnsafeMemory<E, Use>` at base + i*stride (no load).
        if self._is_unsafe_memory(container_type):
            return self._check_um_index_projection(expr, container_type)
        # design 141: a struct may declare `func [](...) borrows -> T`, which
        # makes `v[i]` a PLACE. Intercept before the Int-index rule below — an
        # accessor's parameter is whatever it declared (`Map.[]` takes a key),
        # and its own checking happens against that declaration.
        if container_type.kind == TypeKind.STRUCT:
            place = self._check_place_index(expr, container_type)
            if place is not None:
                return place
        index_type = self._check_expression(expr.index)
        if index_type is None:
            return None
        index_underlying = self._get_underlying_type(index_type)
        if index_underlying.kind != TypeKind.INT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"index must be Int, got `{index_type}`",
                expr.index.line, expr.index.column
            )
            return None
        if container_type.kind == TypeKind.ARRAY:
            # Reject out-of-range compile-time constant indices, mirroring the
            # tuple-index path below. Dynamic indices stay unchecked.
            if isinstance(expr.index, IntLiteral) and container_type.array_size is not None:
                if expr.index.value < 0 or expr.index.value >= container_type.array_size:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"array index {expr.index.value} out of range for array with "
                        f"{container_type.array_size} elements",
                        expr.line, expr.column
                    )
                    return None
            return container_type.array_element_type
        elif container_type.kind == TypeKind.TUPLE:
            if not isinstance(expr.index, IntLiteral):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "tuple index must be a compile-time constant",
                    expr.index.line, expr.index.column
                )
                return None
            index = expr.index.value
            if container_type.element_types is None:
                return None
            if index < 0 or index >= len(container_type.element_types):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"tuple index {index} out of range for tuple with {len(container_type.element_types)} elements",
                    expr.line, expr.column
                )
                return None
            return container_type.element_types[index]
        elif container_type.kind == TypeKind.POINTER:
            # Raw-pointer deref. Reaching a pointer to index it already marked
            # the enclosing function under the design-130 trigger rule, so the
            # deref itself carries no separate obligation.
            #
            # design 219 unit A2: this is where the place's ROOT kind is known,
            # so it is where the "no occupancy is tracked here" stamp is set.
            # See `_place_move_out_type` for what reads it.
            expr.pointer_place = True
            return container_type.inner_type
        else:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index into type `{container_type}`",
                expr.line, expr.column
            )
            return None

    # =====================================================================
    # UnsafeMemory<T, Use> — typed memory at a fixed address (design 46)
    # =====================================================================

    # Types that a Device register view may `read()`/`write()`: whole-struct and
    # whole-array access is forbidden (multi-register access is never atomic).
    _UM_SCALAR_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT, TypeKind.BOOL, TypeKind.FLOAT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    })

    def _is_unsafe_memory(self, t: Optional[SawType]) -> bool:
        return (t is not None and t.kind == TypeKind.STRUCT
                and t.struct_name == "UnsafeMemory")

    def _um_view_and_use(self, t: SawType):
        """(viewed-type T, Use-marker) for a `UnsafeMemory<T, Use>`; (None, None)
        if the type is not fully parameterized."""
        args = t.type_args or []
        if len(args) < 2:
            return (None, None)
        return (args[0], args[1])

    def _um_use_name(self, use: Optional[SawType]) -> Optional[str]:
        if use is not None and use.kind == TypeKind.STRUCT:
            return use.struct_name
        return None

    def _um_unwrap_marker(self, view: SawType):
        """Peel a `ReadOnly<T>`/`WriteOnly<T>` field marker off a projected view,
        returning `(inner_scalar_type, mode)` with mode in {'ro','wo','rw'}."""
        if (view is not None and view.kind == TypeKind.STRUCT
                and view.struct_name in ("ReadOnly", "WriteOnly")
                and view.type_args):
            mode = 'ro' if view.struct_name == "ReadOnly" else 'wo'
            return (view.type_args[0], mode)
        return (view, 'rw')

    def _um_is_scalar(self, t: SawType) -> bool:
        return t is not None and t.kind in self._UM_SCALAR_KINDS

    def _validate_unsafe_memory_type(self, t: SawType, line: int, column: int) -> bool:
        """Enforce the shape `UnsafeMemory<T, Use>` with `Use` an EXPLICIT intent
        marker (`Device` or `Normal`) — no default (design 46)."""
        args = t.type_args or []
        if len(args) != 2:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                "`UnsafeMemory` takes exactly two type arguments: the viewed type "
                "and the intent marker `Device` or `Normal`",
                line, column,
                hint="the intent marker is EXPLICIT — write `UnsafeMemory<T, Device>` "
                     "or `UnsafeMemory<T, Normal>`"
            )
            return False
        use_name = self._um_use_name(args[1])
        if use_name not in ("Device", "Normal"):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"the intent marker of `UnsafeMemory` must be `Device` or `Normal`, "
                f"got `{args[1]}`",
                line, column,
                hint="`Device` = volatile register block; `Normal` = plain RAM region"
            )
            return False
        return True

    def _check_um_projection(self, expr: MemberAccess, um_type: SawType) -> Optional[SawType]:
        """Project `UM<Struct, Use>.field` -> `UM<Field, Use>` (design 46)."""
        view, use = self._um_view_and_use(um_type)
        if view is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "cannot project through an under-specified `UnsafeMemory` type",
                expr.line, expr.column)
            return None
        if view.kind != TypeKind.STRUCT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access field `{expr.member}` — the memory views `{view}`, "
                f"not a struct",
                expr.line, expr.column)
            return None
        struct_info = self.get_struct_info(view.struct_name, from_type=view)
        if struct_info is None or expr.member not in struct_info.fields:
            avail = ', '.join(struct_info.field_order) if struct_info else ''
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{view.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=f"available fields: {avail}" if avail else None)
            return None
        field_type = self._resolve_type(struct_info.fields[expr.member])
        expr.um_projection = True
        return SawType(TypeKind.STRUCT, struct_name="UnsafeMemory",
                       type_args=[field_type, use])

    def _check_um_index_projection(self, expr: ArrayIndex, um_type: SawType) -> Optional[SawType]:
        """Project `UM<[E; N], Use>[i]` -> `UM<E, Use>` (design 46)."""
        view, use = self._um_view_and_use(um_type)
        index_type = self._check_expression(expr.index)
        if index_type is not None and self._get_underlying_type(index_type).kind != TypeKind.INT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"index must be Int, got `{index_type}`",
                expr.index.line, expr.index.column)
            return None
        if view is None or view.kind != TypeKind.ARRAY:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index a `UnsafeMemory` view of non-array type `{view}`",
                expr.line, expr.column)
            return None
        if (isinstance(expr.index, IntLiteral) and view.array_size is not None
                and (expr.index.value < 0 or expr.index.value >= view.array_size)):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"array index {expr.index.value} out of range for region with "
                f"{view.array_size} elements",
                expr.line, expr.column)
            return None
        expr.um_projection = True
        return SawType(TypeKind.STRUCT, struct_name="UnsafeMemory",
                       type_args=[view.array_element_type, use])

    def _check_interior_cell_method(self, expr: MethodCall,
                                    payload: SawType) -> Optional[SawType]:
        """Check the one accessor an interior-mutability cell has (design 186).

        `ptr(&self) unsafe -> UnsafePointer<T>` and nothing else. Every other
        name is a clean error rather than a member-lookup failure, because the
        cell's surface being exactly one method is the reason a reviewer can
        read a cell-carrying type and know where its mutation happens.
        """
        if expr.method_name != "ptr":
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"`UnsafeMutableInterior<{payload}>` has no method "
                f"`{expr.method_name}`",
                expr.line, expr.column,
                hint="a cell has exactly one accessor, `ptr()` — reach the "
                     "value through the pointer it returns")
            return None
        if expr.arguments:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                "`ptr()` takes no arguments", expr.line, expr.column)
            return None
        expr.interior_cell_ptr = True
        # MUTABLE: writing through it is the whole point of a cell. That the
        # receiver is `&self` is exactly what interior mutability means.
        return SawType(TypeKind.POINTER, inner_type=payload,
                       pointer_mutable=True)

    def _check_um_method(self, expr: MethodCall, um_type: SawType) -> Optional[SawType]:
        """Check a `read`/`write`/`ptr`/`len`/`end` accessor on `UnsafeMemory`."""
        view, use = self._um_view_and_use(um_type)
        use_name = self._um_use_name(use)
        method = expr.method_name
        if view is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "cannot access an under-specified `UnsafeMemory` value",
                expr.line, expr.column)
            return None
        expr.um_volatile = (use_name == "Device")

        if method in ("read", "write"):
            inner, mode = self._um_unwrap_marker(view)
            if use_name == "Device":
                if not self._um_is_scalar(inner):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"Device memory has no whole-`{view}` access — multi-register "
                        f"access is never atomic; project a scalar register field",
                        expr.line, expr.column,
                        hint="access one register at a time (`REGS.field.read()`)")
                    return None
                if method == "read" and mode == 'wo':
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "cannot `read()` a `WriteOnly` register",
                        expr.line, expr.column)
                    return None
                if method == "write" and mode == 'ro':
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "cannot `write()` a `ReadOnly` register",
                        expr.line, expr.column)
                    return None
            else:
                # Normal: plain access; whole-struct / element allowed. Markers
                # are a Device-only concept, so the inner type is the view itself.
                inner = view
            expr.um_method = method
            expr.um_scalar_type = inner
            if method == "read":
                if len(expr.arguments) != 0:
                    self._error(ErrorKind.WRONG_ARGUMENT_COUNT,
                                "`read()` takes no arguments", expr.line, expr.column)
                    return None
                return inner
            # write(v)
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(ErrorKind.WRONG_ARGUMENT_COUNT,
                            "`write(v)` takes exactly one positional argument",
                            expr.line, expr.column)
                return None
            # Design 87: `reg.write(0)` is a bare literal in a typed slot like
            # any other, and this path never stamped the expectation — the
            # platform-pair permission absorbed the `Int`/`UInt32` mismatch that
            # left. Stamped here, so the no-suffix-where-an-expected-type-is-in
            # -force idiom keeps working in a driver (design 205).
            self._apply_literal_expected_type(expr.arguments[0].value, inner)
            val_type = self._check_expression(expr.arguments[0].value)
            if val_type is not None and not self._transfer_compatible(val_type, inner):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`write` expects `{inner}`, got `{val_type}`",
                    expr.line, expr.column,
                    hint=self._int_conversion_hint(val_type, inner))
            return SawType(TypeKind.VOID)

        # Region accessors — Normal only.
        if method in ("ptr", "len", "end"):
            if use_name != "Normal":
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{method}()` is a `Normal` region accessor; it is not available "
                    f"on `Device` memory",
                    expr.line, expr.column,
                    hint="Device registers are accessed with `read()`/`write()`")
                return None
            if len(expr.arguments) != 0:
                self._error(ErrorKind.WRONG_ARGUMENT_COUNT,
                            f"`{method}()` takes no arguments", expr.line, expr.column)
                return None
            expr.um_method = method
            if method == "ptr":
                return SawType(TypeKind.POINTER,
                               inner_type=SawType(TypeKind.INT8), pointer_mutable=True)
            if method == "end":
                return SawType(TypeKind.POINTER,
                               inner_type=SawType(TypeKind.INT8), pointer_mutable=True)
            # len(): region byte length
            if view.kind != TypeKind.ARRAY:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`len()` needs an array region view, got `{view}`",
                    expr.line, expr.column)
                return None
            return SawType(TypeKind.INT)

        self._error(
            ErrorKind.UNDEFINED_FUNCTION,
            f"`UnsafeMemory` has no method `{method}`",
            expr.line, expr.column,
            hint="Device: `read()`/`write(v)`; Normal: also `ptr()`/`len()`/`end()`")
        return None

    def _check_field_visible(self, struct_info, field_name: str,
                             type_name: str, expr) -> None:
        """Member visibility gate (design 80): a struct field is private-by-default
        outside its defining module. Compiler-synthesized access is exempt by
        provenance — the gate enforces SOURCE-level access only.

        Provenance comes from the enclosing function alone. There was also a
        per-node `synthesized_access` flag tested here, but nothing in the
        compiler ever set it (design 126 R1 removed it): it read as a second
        exemption route and was always False."""
        if self._in_synthesized_context():
            return
        def_module = getattr(struct_info, 'def_module', ())
        fv = getattr(struct_info, 'field_visibility', None) or {}
        vis = fv.get(field_name, Visibility.PRIVATE)
        if not self._member_gate_allows(def_module, vis):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"field `{field_name}` of struct `{type_name}` is {self._vis_word(vis)} "
                f"and not accessible from this module",
                expr.line, expr.column,
                hint=f"mark it `public` in the declaration of `{type_name}` to expose it")

    def _check_method_visible(self, struct_name: str, method_name: str,
                              method_info, expr) -> None:
        """Member visibility gate (design 80) for an extension method / init /
        static. Private-by-default outside the defining module; a method that
        satisfies a conformed trait's requirement is always callable (trait
        dispatch). A synthesized enclosing function is exempt by provenance."""
        if method_info is None:
            return
        if self._in_synthesized_context():
            return
        if getattr(method_info, 'satisfies_trait', False):
            return
        def_module = getattr(method_info, 'def_module', ())
        vis = getattr(method_info, 'visibility', Visibility.PRIVATE)
        if not self._member_gate_allows(def_module, vis):
            kind = "initializer" if getattr(method_info, 'is_init', False) else \
                   ("static method" if getattr(method_info, 'is_static', False)
                    else "method")
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"{kind} `{method_name}` of `{struct_name}` is {self._vis_word(vis)} "
                f"and not accessible from this module",
                expr.line, expr.column,
                hint=f"mark it `public` in the extension of `{struct_name}` to expose it")

    def _check_arguments_anyway(self, expr) -> None:
        """Type-check a failed call's own ARGUMENTS, for their diagnostics alone
        (DF-232p).

        A call that cannot resolve — refused by visibility, or naming a symbol
        the module does not export — returns before the argument list is ever
        looked at, so every refusal INSIDE it is swallowed:
        `uart.write_str(hal.arch_name())` with both refused reported only
        `write_str`. That is not a wart but a census hazard: DF-232q measured a
        visibility survey under-counting by 72 sites across three waves,
        precisely because each failing outer form hid what was nested in it.

        ENTRY POINTS (obligation 1) — every place a call bails while holding an
        unchecked argument list:
          * `_check_method_call`'s CHAINED module arm (`pkg.mod.f(...)`), on both
            of its exits: the refusal/absence one and the not-callable one.
          * `_check_method_call`'s QUALIFIER module arm (`mod.f(...)`), on all
            three: refusal/absence, the enum-spelling error, and not-callable.

        The member-visibility gate is deliberately NOT an entry point: it
        REPORTS and lets the call go on, so its arguments are checked by the
        ordinary path already.

        Errors from the arguments are reported by the walk itself; the result
        types are of no use to a call that is not happening.
        """
        for arg in getattr(expr, 'arguments', ()) or ():
            value = getattr(arg, 'value', None)
            if value is not None:
                self._check_expression(value)

    def _check_member_access(self, expr: MemberAccess) -> Optional[SawType]:
        """Check member access for struct fields, enum variants, or module symbols."""
        # design 257 §2, the `BinaryOp`/`UnaryOp` rule's third twin: the
        # adoption funnel folded this LONE raw-backed enum case against an
        # integer slot and range-checked it there, so it IS that type — asking
        # the member would answer the ENUM, which is the refusal DF-282b
        # reported. `expected_type` is read rather than `resolved_type` for the
        # reason `_check_binary_op` gives: the place lowering unchecks the tree
        # between the front half's two passes, so only the funnel's own
        # annotations survive to the second.
        folded_type = expr.expected_type
        if (expr.const_folded_value is not None
                and self._const_adoption_slot(folded_type)):
            expr.resolved_type = SawType(folded_type.kind)
            return expr.resolved_type
        if isinstance(expr.object, MemberAccess):
            obj_type = self._check_member_access(expr.object)
            # Design 40 item 3 (L6): this recursion bypasses the
            # `_check_expression` chokepoint, so the nested module-qualified
            # object node would otherwise reach codegen without a
            # `resolved_type`. Stamp it here (the module member-access checker)
            # so signedness/type-driven lowering never falls back for these.
            if obj_type is not None:
                expr.object.resolved_type = obj_type
            if obj_type and obj_type.kind == TypeKind.MODULE:
                inner_module_sym = getattr(expr.object, 'resolved_module_symbol', None)
                if inner_module_sym and inner_module_sym.namespace:
                    from namespace import SymbolKind
                    # DF-232j: the accessor is the module of the code being
                    # checked, and a refused reach reports the TIER rather than
                    # falling through to "has no symbol".
                    refusals = []
                    symbol = inner_module_sym.namespace.resolve(
                        expr.member, check_visibility=True,
                        accessor_module=self._accessor_vis_module(),
                        through_import=True, refusals=refusals
                    )
                    if symbol is None:
                        surface_hint = self._not_reexported_hint(
                            inner_module_sym.namespace, expr.member,
                            obj_type.module_name)
                        if self._report_visibility_refusal(
                                refusals, expr.line, expr.column,
                                surface_hint):
                            return None
                        self._error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"module `{obj_type.module_name}` has no symbol `{expr.member}`",
                            expr.line, expr.column,
                            hint=surface_hint
                        )
                        return None
                    if symbol.kind == SymbolKind.STRUCT:
                        # Design 144: carry the identity, not the spelling.
                        _id = getattr(symbol, 'type_identity', "") or expr.member
                        expr.resolved_struct_name = _id
                        expr.resolved_module = obj_type.module_name
                        expr.names_type = True  # DF-236a
                        return SawType(TypeKind.STRUCT, struct_name=_id, symbol=symbol)
                    elif symbol.kind == SymbolKind.ENUM:
                        _id = getattr(symbol, 'type_identity', "") or expr.member
                        expr.resolved_module = obj_type.module_name
                        expr.names_type = True  # DF-236a
                        return SawType(TypeKind.ENUM, enum_name=_id, symbol=symbol)
                    elif symbol.kind == SymbolKind.FUNCTION:
                        expr.resolved_module = obj_type.module_name
                        return SawType(TypeKind.FUNCTION,
                                     param_types=symbol.param_types,
                                     func_return_type=symbol.return_type)
                    elif symbol.kind == SymbolKind.MODULE:
                        expr.resolved_module_symbol = symbol
                        return SawType(TypeKind.MODULE, module_name=expr.member)
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot use `{expr.member}` as an expression",
                            expr.line, expr.column
                        )
                        return None
            elif (obj_type and obj_type.kind == TypeKind.ENUM
                    and getattr(expr.object, 'names_type', False)):
                # Handle module-qualified enum variant access: lib.Color.Red
                # DF-236a: gated on `names_type` for the reason the method-call
                # arms are — a FIELD READ at enum type produces the same ENUM
                # type as the qualified type name does, so `h.color.Red` used to
                # build a fresh `Color.Red` here, discarding the receiver it was
                # written on, and the program ran.
                enum_info = self.get_enum_info(obj_type.enum_name, from_type=obj_type)
                if enum_info:
                    type_args = obj_type.type_args
                    if expr.member in enum_info.variants:
                        variant_params = enum_info.variants[expr.member]
                        if len(variant_params) == 0:
                            # Constructs a value rather than reading one out of
                            # storage — see the unqualified path (design 139).
                            expr.enum_variant_literal = True
                            self._stamp_enum_raw_value(expr, enum_info)
                            _eid = self._sym_identity(enum_info,
                                                      obj_type.enum_name)
                            expr.resolved_type_identity = _eid
                            result = SawType(TypeKind.ENUM, enum_name=_eid, type_args=type_args, symbol=enum_info)
                            # Preserve module resolution info for codegen
                            if getattr(expr.object, 'resolved_module', None) is not None:
                                expr.resolved_module = expr.object.resolved_module
                            return result
                        else:
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"variant `{expr.member}` has associated values and must be called like `{obj_type.enum_name}.{expr.member}(...)`",
                                expr.line, expr.column
                            )
                            return None
                    else:
                        self._error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"enum `{obj_type.enum_name}` has no variant `{expr.member}`",
                            expr.line, expr.column
                        )
                        return None
        if isinstance(expr.object, Identifier):
            # Design 53: integer limits `Int.max` / `Int.min` and `.max`/`.min`
            # on every fixed-width type. The result has the named integer type;
            # the platform-`Int` bounds are materialized at codegen (target word).
            limit_kind = self._INT_LIMIT_TYPE_KINDS.get(expr.object.name)
            if limit_kind is not None and expr.member in ("max", "min"):
                expr.int_limit = (expr.object.name, expr.member)
                return SawType(limit_kind)

            # Design 150 pin 4: a value binding of this name wins; the qualifier
            # is consulted last.
            module_sym = self._module_qualifier(expr.object.name)
            if module_sym and module_sym.namespace:
                from namespace import SymbolKind
                # DF-232j: see the chained arm above.
                refusals = []
                symbol = module_sym.namespace.resolve(
                    expr.member, check_visibility=True,
                    accessor_module=self._accessor_vis_module(),
                    through_import=True, refusals=refusals
                )
                if symbol is None:
                    surface_hint = self._not_reexported_hint(
                        module_sym.namespace, expr.member, expr.object.name)
                    if self._report_visibility_refusal(
                            refusals, expr.line, expr.column, surface_hint):
                        return None
                    self._error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"module `{expr.object.name}` has no symbol `{expr.member}`",
                        expr.line, expr.column,
                        hint=surface_hint
                    )
                    return None
                if symbol.kind == SymbolKind.STATIC:
                    # Module-qualified static read (design 41): `mod.NAME`. Codegen
                    # resolves the same static in the merged namespace by simple
                    # name, so tag the member for it and read like a binding.
                    expr.resolved_static_name = expr.member
                    expr.resolved_module = expr.object.name
                    # design 149: naming an `unsafe static var` is unsafe
                    # contact through the qualified spelling too.
                    if getattr(symbol, 'is_var', False):
                        self._note_unsafe_static_contact(
                            f"{expr.object.name}.{expr.member}", expr)
                    return symbol.type
                if symbol.kind == SymbolKind.STRUCT:
                    # Design 144: carry the identity, not the spelling.
                    _id = getattr(symbol, 'type_identity', "") or expr.member
                    expr.resolved_struct_name = _id
                    expr.resolved_module = expr.object.name
                    expr.names_type = True  # DF-236a
                    return SawType(TypeKind.STRUCT, struct_name=_id, symbol=symbol)
                elif symbol.kind == SymbolKind.ENUM:
                    _id = getattr(symbol, 'type_identity', "") or expr.member
                    expr.resolved_module = expr.object.name
                    expr.names_type = True  # DF-236a
                    return SawType(TypeKind.ENUM, enum_name=_id, symbol=symbol)
                elif symbol.kind == SymbolKind.FUNCTION:
                    expr.resolved_module = expr.object.name
                    return SawType(TypeKind.FUNCTION,
                                 param_types=symbol.param_types,
                                 func_return_type=symbol.return_type)
                elif symbol.kind == SymbolKind.MODULE:
                    expr.resolved_module_symbol = symbol
                    return SawType(TypeKind.MODULE, module_name=expr.member)
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot use `{expr.member}` as an expression",
                        expr.line, expr.column
                    )
                    return None
            enum_info = self.get_enum_info(expr.object.name)
            if enum_info:
                type_args = expr.object.type_args
                if enum_info.type_params:
                    if not type_args:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"generic enum `{expr.object.name}` requires type arguments",
                            expr.line, expr.column,
                            hint=f"use `{expr.object.name}<...>.{expr.member}`"
                        )
                    elif len(type_args) != len(enum_info.type_params):
                        self._error(
                            ErrorKind.WRONG_ARGUMENT_COUNT,
                            f"expected {len(enum_info.type_params)} type argument(s), got {len(type_args)}",
                            expr.line, expr.column
                        )
                if expr.member in enum_info.variants:
                    variant_params = enum_info.variants[expr.member]
                    if len(variant_params) == 0:
                        # A payload-free variant CONSTRUCTS a value; it does not
                        # read one out of storage (design 139).
                        expr.enum_variant_literal = True
                        self._stamp_enum_raw_value(expr, enum_info)
                        expr.resolved_type_identity = self._sym_identity(
                            enum_info, expr.object.name)
                        return SawType(TypeKind.ENUM,
                                       enum_name=expr.resolved_type_identity,
                                       type_args=type_args, symbol=enum_info)
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"variant `{expr.member}` has associated values and must be called like `{expr.object.name}.{expr.member}(...)`",
                            expr.line, expr.column
                        )
                        return None
                else:
                    self._error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"enum `{expr.object.name}` has no variant `{expr.member}`",
                        expr.line, expr.column
                    )
                    return None
        obj_type = self._check_expression(expr.object)
        if obj_type is None:
            return None
        # Named-tuple field access (design 63): `p.x` resolves to the position of
        # `x` in the tuple's label list, returning that element's type. Positional
        # `.0` / `[0]` keep working via the tuple-index path.
        obj_resolved = self._resolve_type_alias(obj_type)
        if (obj_resolved.kind == TypeKind.TUPLE and obj_resolved.tuple_field_names
                and expr.member in obj_resolved.tuple_field_names):
            idx = obj_resolved.tuple_field_names.index(expr.member)
            expr.tuple_field_index = idx  # stamp for codegen
            return obj_resolved.element_types[idx]
        # A distinct `type` over a non-struct underlying (e.g. `type MyInt = Int`)
        # has no fields, and the `.value` underlying-accessor is not a language
        # feature (the spec labels it planned/illustrative, ledger L16). Accessing
        # a member on one used to reach codegen and ICE ("Cannot find field ...
        # in struct with type i64"); emit a clean typechecker error instead. (A
        # distinct alias of a struct falls through to the normal field check.)
        if obj_type.kind == TypeKind.STRUCT and obj_type.struct_name is not None:
            alias_sym = self.get_type_alias_info(obj_type.struct_name)
            if alias_sym is not None:
                underlying = self._resolve_type_alias(obj_type)
                if underlying is None or underlying.kind != TypeKind.STRUCT:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot access member `{expr.member}` on the distinct "
                        f"type `{obj_type.struct_name}`: it has no fields and there "
                        f"is no `.value` accessor — a distinct type flows to its "
                        f"underlying type implicitly (use it directly), or project "
                        f"it explicitly with a cast like `x as {underlying}`",
                        expr.line, expr.column,
                    )
                    return None
        # design 46: member access on `UnsafeMemory<Struct, Use>` PROJECTS to
        # `UnsafeMemory<Field, Use>` at base + compile-time offset — the shared
        # projection engine. No memory is loaded.
        if self._is_unsafe_memory(obj_type):
            return self._check_um_projection(expr, obj_type)
        if obj_type.kind != TypeKind.STRUCT:
            # DF-236a: `h.color.Red` names a VARIANT through a VALUE of the enum.
            # Say that, rather than "cannot access member of non-struct type" —
            # the reader did not think they were reading a field, and this
            # spelling used to CONSTRUCT a fresh variant and discard the
            # receiver.
            if obj_type.kind == TypeKind.ENUM and obj_type.enum_name is not None:
                _enum = self.get_enum_info(obj_type.enum_name, from_type=obj_type)
                if _enum is not None and expr.member in _enum.variants:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`{expr.member}` is a variant of enum "
                        f"`{obj_type.enum_name}` and cannot be reached through "
                        f"a value",
                        expr.line, expr.column,
                        hint=f"name it on the type: "
                             f"`{obj_type.enum_name}.{expr.member}`; to ask "
                             f"which variant a value holds, `match` it")
                    return None
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access member of non-struct type `{obj_type}`",
                expr.line, expr.column
            )
            return None
        if obj_type.struct_name is None:
            return None
        struct_info = self.get_struct_info(obj_type.struct_name, from_type=obj_type)
        if struct_info is None:
            return None
        if expr.member not in struct_info.fields:
            # Design 150 pin 4: name the shadowing declaration when one took the
            # qualifier this projection was reaching for.
            shadow = self._qualifier_shadow_hint(expr.object, expr.member)
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{obj_type.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=shadow or
                     f"available fields: {', '.join(struct_info.field_order)}"
            )
            return None
        self._check_field_visible(struct_info, expr.member,
                                  obj_type.struct_name, expr)
        # Resolve the field type (e.g., convert STRUCT to ENUM if needed).
        field_type = struct_info.fields[expr.member]
        # design 74 (A5-rest, shape 2): if the receiver is a concrete instantiation
        # of a GENERIC struct but `struct_info` is the generic symbol (its fields
        # carry the abstract `T`), substitute the struct's type params with the
        # receiver's type args so `self.value` on a `Holder<Int>` resolves to `Int`.
        # Normal instantiations carry a monomorphized symbol (concrete fields, no
        # type_params) and skip this.
        tps = getattr(struct_info, 'type_params', None)
        if tps and getattr(obj_type, 'type_args', None):
            type_map = {tp.name: arg for tp, arg in zip(tps, obj_type.type_args)}
            if type_map:
                field_type = field_type.substitute(type_map)
        return self._resolve_type(field_type)

    def _check_init_field_value(self, value, expected_type: Optional[SawType]) -> Optional[SawType]:
        """Type-check a struct-init field/init-argument value.

        When the field/parameter type is a function type and the value is a
        closure literal, infer the closure's parameter types from that expected
        type — mirroring the call-argument path in `_check_field_call`
        (`{ $0 * 2 }` gets its `$0: Int` from the field's `(Int) -> ...`). A
        closure stored in a struct field escapes its creating frame, so it is
        NOT treated as a direct call argument (`as_call_argument` stays False),
        which correctly routes it through escaping-closure heap-env handling.
        """
        if (isinstance(value, ClosureExpr) and expected_type is not None
                and expected_type.kind == TypeKind.FUNCTION):
            return self._check_closure(value, expected_type)
        # design 54: a collection/array literal in a struct field gets the field
        # type as its expected type (build a Vector/Map/Set, custom allocator).
        self._apply_literal_expected_type(value, expected_type)
        return self._check_expression(value)

    def _fill_or_report_type_args(self, provided, type_params, what, line, column):
        """Design 37 — validate type-argument arity, filling omitted trailing
        arguments from their declared defaults.

        Returns the fully-applied argument list (length == len(type_params)), or
        None after reporting a precise arity error. `what` is a noun phrase such
        as ``struct `Vector` ``. Too many args, or too few with no default on a
        missing trailing parameter, are the two error cases of design 37 item 1.
        """
        n = len(type_params)
        provided = list(provided or [])
        if len(provided) == n:
            return self._finish_type_args(provided, type_params, what, line, column)
        if len(provided) > n:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"{what} expected {n} type argument(s), got {len(provided)}",
                line, column
            )
            return None
        # Fewer than declared: every omitted trailing parameter must have a
        # default. Defaults are resolved (and thus themselves default-filled).
        missing = type_params[len(provided):]
        if all(getattr(tp, 'default', None) is not None for tp in missing):
            filled = list(provided)
            for tp in missing:
                filled.append(self._resolve_type(tp.default))
            return self._finish_type_args(filled, type_params, what, line, column)
        if not provided:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"generic {what} requires type arguments",
                line, column,
            )
            return None
        first_no_default = next(
            tp for tp in missing if getattr(tp, 'default', None) is None)
        self._error(
            ErrorKind.WRONG_ARGUMENT_COUNT,
            f"{what} expected {n} type argument(s), got {len(provided)} "
            f"(type parameter `{first_no_default.name}` has no default)",
            line, column
        )
        return None

    def _finish_type_args(self, args, type_params, what, line, column):
        """Canonicalize a fully-applied argument list (design 148).

        This is the chokepoint every reference site funnels through, so it is
        where a const argument written as ARITHMETIC becomes a number:
        `Ring<2 * 128>` and `Ring<256>` have to be the same instantiation, and
        they are only if the value is folded before anything mangles or
        monomorphizes it — the same rule design 37 applies to defaults.
        """
        folded = [self._fold_const_arg(a) for a in args]
        folded = self._const_static_args(folded, type_params)
        self._check_const_arg_kinds(folded, type_params, what, line, column)
        return folded

    def _const_static_args(self, args, type_params):
        """A bare NAME on a const parameter may be a module `static` (DF-172j).

        `FixedBuf<CAP * 2>` already arrives as a value — the parser's retry
        reads anything followed by an operator as a constant expression — but a
        bare `FixedBuf<CAP>` is genuinely ambiguous at parse time and stays a
        TYPE until something knows the parameter it lands on. That is here, the
        same place a forwarded const parameter (`FixedBuf<N>` inside `extension
        FixedBuf<N>`) is recognized, so the static is recognized beside it: it
        folds to a number BEFORE mangling, and `FixedBuf<CAP>` and
        `FixedBuf<16>` are then one instantiation with one symbol.
        """
        from ast_nodes import IntLiteral
        out = list(args)
        for i, (tp, arg) in enumerate(zip(type_params, args)):
            if not getattr(tp, 'is_const', False):
                continue
            if arg is None or arg.kind != TypeKind.STRUCT or arg.type_args:
                continue
            name = arg.struct_name
            if not name or name in self._const_param_types():
                continue
            value, _reason = self._const_static_lookup(name)
            if value is None:
                continue
            out[i] = SawType(TypeKind.CONST_VALUE, const_value=value,
                             array_size_expr=IntLiteral(value=value))
        return out

    def _fold_const_arg(self, arg):
        """Give a CONST_VALUE argument its integer, if it does not have one."""
        if (arg is None or arg.kind != TypeKind.CONST_VALUE
                or arg.const_value is not None):
            return arg
        value = self._try_const_value(arg.array_size_expr)
        if value is None:
            return arg
        import dataclasses
        return dataclasses.replace(arg, const_value=value)

    def _check_const_arg_kinds(self, args, type_params, what, line, column):
        """A const parameter takes a VALUE and a type parameter takes a TYPE.

        Written as its own check (design 148) because the two mistakes read as
        nothing else otherwise: `FixedBuf<Int>` would fail as an undefined
        length somewhere inside the type, and `Vector<4>` as an undefined type
        named `4`. Both are one confusion — the two parameter kinds look alike
        at a use site — so both name the parameter and what it wants.
        """
        for tp, arg in zip(type_params, args):
            if arg is None:
                continue
            is_const_param = getattr(tp, 'is_const', False)
            is_value = arg.kind == TypeKind.CONST_VALUE
            if is_const_param and not is_value:
                # A bare name is how a const parameter is FORWARDED from an
                # enclosing generic (`FixedBuf<N>` inside `extension
                # FixedBuf<N>`), so a name that is one in scope is correct here.
                if (arg.kind == TypeKind.STRUCT
                        and arg.struct_name in self._const_param_types()):
                    continue
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"{what} takes a VALUE for the const parameter "
                    f"`{tp.name}`, and `{arg}` is a type",
                    line, column,
                    hint=f"write a compile-time integer — `{tp.name}` is "
                         f"declared `const {tp.name}: {tp.const_type}`")
            elif is_value and not is_const_param:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"{what} takes a TYPE for the parameter `{tp.name}`, and "
                    f"`{arg}` is a value",
                    line, column,
                    hint=f"declare it `const {tp.name}: Int` to take a value")

    _FIXED_INT_RANGES = {
        TypeKind.INT8: (-(1 << 7), (1 << 7) - 1),
        TypeKind.INT16: (-(1 << 15), (1 << 15) - 1),
        TypeKind.INT32: (-(1 << 31), (1 << 31) - 1),
        TypeKind.INT64: (-(1 << 63), (1 << 63) - 1),
        TypeKind.UINT8: (0, (1 << 8) - 1),
        TypeKind.UINT16: (0, (1 << 16) - 1),
        TypeKind.UINT32: (0, (1 << 32) - 1),
        TypeKind.UINT64: (0, (1 << 64) - 1),
    }

    def _apply_shift_expected_type(self, expr, rt) -> None:
        """Push an integer expectation through a SHIFT to its shiftee (design 205).

        `<<` and `>>` are the one binary operator whose two operands are not
        peers: design 195 exempts the COUNT, which is range-checked against the
        left operand's width and contributes nothing to the result's type. So a
        shift forwards its left operand's type, and an expected type reaches
        that operand the way it reaches a unary minus's.

        Called from `_apply_literal_expected_type`'s cases (2b) and (2c) —
        the first for a fixed-width slot whose whole expression did not fold,
        the second for a platform slot, which (2b) never took. A non-shift
        operator is left alone: its two operands ARE peers, and stamping one of
        them would decide the agreement rule's question for it.
        """
        from ast_nodes import BinaryOp as _BinaryOp
        if isinstance(expr, _BinaryOp) and expr.op in ('<<', '>>'):
            self._apply_literal_expected_type(expr.left, rt)

    def _const_adoption_slot(self, rt) -> bool:
        """Is this slot an ADOPTION TARGET for a constant expression?

        THE slot predicate of the adoption ladder (DF-235a/b -> DF-240a ->
        DF-243a), asked at every arm that folds. Design 257 §1 widened it from
        the fixed widths alone to EVERY integer slot: a platform `Int`/`UInt`
        is an adoption target exactly as a `UInt32` is.

        DF-235a/b drew the line at the fixed widths on the reasoning that a
        platform expectation "is what the expression already had, so there is
        nothing to adopt and nothing to check". That is true of `Int` and false
        of `UInt` — the fold is in design 185's SIGNED platform-`Int` domain, so
        a `UInt` slot is a real target with a real range check, and
        `static M: UInt = (1 << BITS) - 1` was refused where its `UInt32` twin
        folded (DF-282a, the sawos HANDLE_INDEX_MASK shape). Folding at `Int`
        too costs nothing and keeps one rule: the folded value range-checks
        against the slot either way.

        What does NOT move is which expressions are constants — a RUNTIME
        operand is not one, so design 205's written-conversion rule still
        refuses `let i: Int = u` on a runtime `u: UInt`.
        """
        return rt is not None and rt.kind in self._AGREEMENT_INT_KINDS

    def _const_adoption_shape(self, expr) -> bool:
        """Is this expression a shape the const-adoption arm should TRY?

        THE leaf/operator predicate of the same ladder. An operator expression
        (`(1 << B) - 1`, `Perm.Read | Perm.Write`, `~mask`) has always been on
        it; design 257 §2 added the LONE raw-backed enum CASE, which is a leaf
        and matched no operator shape — so `static X: UInt32 = E.A | E.B`
        folded to 3 while `static Y: UInt32 = E.A` was ``has type `UInt32` but
        its initializer has type `E` ``, and adding a second flag REMOVED a
        cast (DF-282b). A case is a constant of its BACKING in a const
        position (design 185 unit 4's own reading, which the combination
        already relies on); this makes one case and two agree about that.

        Answering the enum question means resolving the member, so the walk
        that does it runs here — `_stamp_const_names` is idempotent, writes
        only its own annotations, and `const_eval` is their only reader (see
        `_fold_const_expression_into`). A member access that is anything else —
        a field read, an `Int.max`, a module `static` — stamps what it always
        stamped and answers False, so it reaches this arm no differently than
        before.
        """
        from ast_nodes import MemberAccess as _MemberAccess
        if isinstance(expr, BinaryOp):
            return True
        if isinstance(expr, UnaryOp) and expr.op == '~':
            return True
        if isinstance(expr, _MemberAccess):
            self._stamp_const_names(expr)
            return expr.enum_raw_value is not None
        return False

    def _fold_const_expression_into(self, expr, rt, expected_type) -> bool:
        """Adopt a CONSTANT expression into an integer slot (DF-235a/b, widened
        by design 257). True when it folded (range-checked and stamped), False
        when the expression is not a constant this pass can answer.

        The other half of `_apply_literal_expected_type`'s case (2b) — kept here,
        beside `_FIXED_INT_RANGES`, because it is the same range check case (1)
        runs on a bare literal, reached from the same funnel.

        Folds through the ONE evaluator (`const_eval.py`), so an expression that
        is constant here is constant in a `static_assert` and in an array length
        too. An expression it cannot answer — a name it was handed no value for,
        a call, anything with a runtime operand in it — raises, and the caller's
        arm simply returns, leaving the expression exactly as it was before this
        case existed. That is what keeps `n * 2` and `word | (1u32 << n)`
        untouched.

        A Bool result is not adopted either: `(a < b)` is a comparison, not an
        integer, and it has no business in an integer slot — the ordinary type
        mismatch reports it, in its own words.

        DF-240a (design 241 unit 2, ruled Aug 21): the NAMES a constant reads
        are supplied here, by the same `_stamp_const_names` walk every other
        const position uses — so an ADOPTION SLOT IS A FULL CONST POSITION. A
        module `static` leaf folds (`let e: UInt16 = 1 << PAGE_SHIFT` is the
        same "does not fit" error `1 << 20` is, which is what the
        size-in-one-place idiom needs), and so does a raw-backed enum CASE
        (`let mask: UInt8 = Perm.Read | Perm.Write` is 3, the BACKING integer —
        design 185 unit 4's own reading in every const position). That is a
        deliberate AMENDMENT to 185 unit 4, not a side effect: what stays
        refused is an operator over enum-typed VALUES anywhere that is NOT a
        const or adoption position, which is where the operands carry no tag.

        Stamping is safe on an expression that turns out NOT to be constant:
        the walk writes `const_static_value` / `enum_raw_value` onto its own
        nodes, `const_eval` is the only reader of either, and a run-time
        operand beside a named one (`LIMIT + n`) still raises and leaves the
        expression exactly as it was.
        """
        from const_eval import const_eval, ConstEvalError
        self._stamp_const_names(expr)
        try:
            value = const_eval(expr, env=self._const_param_env(),
                               width=self.platform_int_width)
        except ConstEvalError:
            return False
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        # A constant that reads a const generic PARAMETER has no value until the
        # instantiation supplies one; the typechecker checks a generic body once,
        # abstractly. Folding here would bake in whatever the abstract probe
        # happened to hold, so it is left alone and monomorphization sees the
        # expression it was written as.
        if self._mentions_const_param(expr):
            return False
        expr.const_folded_value = value
        expr.expected_type = rt
        expr.resolved_type = SawType(rt.kind)
        # design 257 §1: `_int_range_for`, not `_FIXED_INT_RANGES` — the
        # platform pair's range is a fact about the effective TARGET (DF-137d),
        # so a fold into a `UInt` is checked against the target's word exactly
        # as a fold into a `UInt32` is against 32 bits.
        lo, hi = self._int_range_for(rt.kind)
        if not (lo <= value <= hi):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"constant expression {value} does not fit in "
                f"`{expected_type}` (range {lo}..={hi})",
                getattr(expr, 'line', 0), getattr(expr, 'column', 0))
        return True

    def _payload_adopts_int_literal(self, payload) -> bool:
        """Could a bare integer literal adopt this `Result` payload (DF-226e)?

        True for an integer type, through any number of optional layers — a
        `Result<Int32?, Bad>` Ok payload takes the literal just as an `Int32`
        one does, since case (0c) peels the optional on the recursion. An
        opaque generic parameter is a STRUCT here and answers False, so an
        abstract `Result<T, E>` body peels nothing and monomorphizes unchanged.
        """
        if payload is None:
            return False
        resolved = self._resolve_type(payload)
        if resolved is None:
            return False
        while (resolved.kind == TypeKind.OPTIONAL
               and resolved.inner_type is not None):
            resolved = self._resolve_type(resolved.inner_type)
            if resolved is None:
                return False
        return self._int_range_for(resolved.kind) is not None

    def _int_range_for(self, kind):
        """The inclusive literal range for an integer TypeKind, or None.

        DF-137d / DF-140a: platform `Int`/`UInt` are POINTER-WIDTH (design 47),
        so their range is a fact about the effective target rather than a
        constant. `0x80000000` fits a 64-bit `Int` and does not fit a 32-bit one,
        and until this was checked the riscv32 spelling silently wrapped to
        -2147483648 — on the profile where an address constant at or above
        0x8000_0000 is the most ordinary thing a kernel writes.
        """
        fixed = self._FIXED_INT_RANGES.get(kind)
        if fixed is not None:
            return fixed
        w = getattr(self, 'platform_int_width', 64)
        if kind == TypeKind.INT:
            return (-(1 << (w - 1)), (1 << (w - 1)) - 1)
        if kind == TypeKind.UINT:
            return (0, (1 << w) - 1)
        return None

    # `_fixed_width_binop_type` lived here until design 195 unit 2. It was the
    # bare-literal adoption rule in a second copy — fixed widths only, plain
    # literals only, arithmetic only — beside the design-87 propagation every
    # other slot uses. `_check_operand_agreement`'s companion
    # `_adopt_bare_literal_operand` is the one implementation now, and its three
    # gaps (a platform `UInt` operand, a NEGATED literal, comparison position)
    # went with the duplicate.

    def _check_fixed_width_literal(self, value_expr, expected_type, line, column):
        """Reject a bare integer literal that does not fit a fixed-width integer
        target (design 65 followup). A literal adopts the field's type exactly, so
        `Rec(tag: 999)` with `tag: Int8` is a clean range error here rather than a
        codegen ICE. Suffixed literals are already range-checked at lex time.

        DF-137d / DF-140a: platform `Int`/`UInt` are checked here too now, against
        the EFFECTIVE target's pointer width — they used to be skipped entirely,
        so a literal too large for a 32-bit `Int` wrapped in silence."""
        if not isinstance(value_expr, IntLiteral) or getattr(value_expr, 'suffix', None):
            return
        rt = self._resolve_type(expected_type) if expected_type is not None else None
        rng = self._int_range_for(rt.kind) if rt is not None else None
        if rng is None:
            return
        lo, hi = rng
        if not (lo <= value_expr.value <= hi):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"integer literal {value_expr.value} does not fit in "
                f"`{expected_type}` (range {lo}..={hi})",
                line, column)

    def _reinterpret_struct_init_as_call(self, expr: StructInit):
        """Design 66: if `expr.struct_name` names a FUNCTION (free or overloaded),
        build the equivalent fully-labeled `FunctionCall` from the struct-init's
        field inits so a labeled call `f(a: 1, b: 2)` — which the parser routes
        to StructInit — resolves as a call. Returns the FunctionCall, or None
        when the name is not a callable function."""
        name = expr.struct_name
        # The name must be callable-but-not-a-struct: a free/overloaded function,
        # an in-scope binding (a closure value), or a constructible type param.
        # A genuinely-unknown name keeps the "undefined struct" diagnostic.
        is_callable = (
            (self.get_function_info(name) is not None
             or len(self.namespace.lookup_function_overloads(name)) >= 1)
            and self.namespace.is_accessible(name)
        ) or (self.current_scope.lookup(name) is not None) \
          or (name in getattr(self, 'current_type_params', {}))
        if not is_callable:
            return None
        from ast_nodes import FunctionCall as _FC, Argument as _Arg, ReferenceExpr as _Ref
        args = []
        for (n, v) in expr.field_inits:
            # A `&`/`&var` value is only legal in argument position (design 34);
            # struct-init parsing did not mark it, so mark it now that we know
            # this is a call.
            if isinstance(v, _Ref):
                v.in_argument_position = True
            args.append(_Arg(value=v, name=n))
        fc = _FC(name=name, arguments=args, type_args=expr.type_args,
                 line=expr.line, column=expr.column)
        return fc

    def _check_struct_init(self, expr: StructInit) -> Optional[SawType]:
        """Check struct initialization with parameter-based resolution."""
        # Prelude discipline (design 82 Part B): a bare `IoError(...)` /
        # `Data(...)` for a non-prelude std type not imported here is rejected
        # with an import hint (unless it is a labeled call to a function — that
        # reinterpretation still happens below when the name is not a std type).
        if (expr.struct_name in getattr(self, '_std_symbol_file', {})
                and self._std_name_gated(expr.struct_name, expr.line, expr.column)):
            return None
        struct_info = self.get_struct_info(expr.struct_name)
        if struct_info is None:
            # Design 66: `name(label: value, ...)` is syntactically identical to
            # struct init; the parser eagerly builds a StructInit. When the name
            # is actually a FUNCTION (not a struct), this is a fully-labeled
            # function call — reinterpret it as one and delegate. Codegen reads
            # `expr.as_function_call` to emit the call instead of a struct build.
            fc = self._reinterpret_struct_init_as_call(expr)
            if fc is not None:
                expr.as_function_call = fc
                return self._check_function_call(fc)
            # design 229: the name may be one a module this file imports has
            # and does not hand on — a different mistake from an unknown name,
            # and one with two fixes.
            if self._report_bare_not_reexported(expr.struct_name, expr.line,
                                                expr.column):
                return None
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined struct `{expr.struct_name}`",
                expr.line, expr.column
            )
            return None
        # Design 144: `StructInit.struct_name` is a type REFERENCE, so from here
        # on it names the resolved type's identity — codegen builds the layout
        # it was handed rather than re-resolving `Header` against a merged
        # namespace where two of them live.
        expr.struct_name = (getattr(struct_info, 'type_identity', "")
                            or expr.struct_name)
        type_mapping: Dict[str, SawType] = {}
        if struct_info.type_params:
            filled_args = self._fill_or_report_type_args(
                expr.type_args, struct_info.type_params,
                f"struct `{expr.struct_name}`", expr.line, expr.column)
            if filled_args is not None:
                # Canonicalize the node's type args to the fully-applied form
                # (design 37) so codegen mangles the same identity the
                # typechecker validated — `Vector<Int>` and `Vector<Int, Global>`
                # share one monomorphization.
                # A constructor writes its generic arguments in an EXPRESSION,
                # which no declared-type walk reaches — the fourth face of
                # DF-194a. `Vector<dep.Point>()` bound a local whose element type
                # kept the dot, so `v.push(dep.Point(...))` was told the argument
                # expected `dep.Point` and got `Point`. Resolved here, before the
                # list is stamped onto the node and read for the substitution.
                filled_args = [self._resolve_declared_qualified_names(a)
                               for a in filled_args]
                expr.type_args = filled_args
                for type_param, type_arg in zip(struct_info.type_params, filled_args):
                    # A generic ARGUMENT is never a parameter role: it fills a
                    # slot inside a type, and a closure in a container slot
                    # outlives the frame that built it. The declared spellings
                    # reach this through `_stamp_escaping_roles`' own recursion;
                    # a constructor writes its arguments here and nowhere else,
                    # so `var v = Vector<() sync -> Int>()` used to bind an
                    # element type the escape check read as non-escaping
                    # (DF-216e).
                    self._stamp_escaping_roles(type_arg, is_param=False)
                    resolved_arg = self._resolve_type(type_arg)
                    type_mapping[type_param.name] = type_arg
                    # Enforce the struct's declared type-param bounds at
                    # construction (e.g. `Channel<T: Send>` requires a Send `T`),
                    # so a non-conforming instantiation is rejected here rather
                    # than surfacing as a missing monomorphization in codegen.
                    for bound in getattr(type_param, 'bounds', None) or []:
                        if self.get_trait_info(bound) is None:
                            continue  # unknown trait name reported elsewhere
                        if not self._bound_satisfied(resolved_arg, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type argument `{resolved_arg}` does not satisfy "
                                f"bound `{type_param.name}: {bound}` on struct "
                                f"`{expr.struct_name}`",
                                expr.line, expr.column
                            )
        # design 65 (L19): a Map/Set KEY must be copyable-with-retain — the
        # container probes keys by copy (hash / compare / slot inspection), which
        # a NoCopy or move-only-Deinit key cannot balance. Checked here at
        # construction; VALUES are unaffected. Set delegates to Map internally,
        # but this fires at the user-facing `Set<T>()` site; the internal
        # `Map<T, SetMark>` in set.saw is checked with a GENERIC T and passes.
        if expr.struct_name in ("Map", "Set") and expr.type_args:
            self._check_map_key_copyable(
                self._resolve_type(expr.type_args[0]), expr,
                "map key" if expr.struct_name == "Map" else "set element")
        provided_params = {field_name for field_name, _ in expr.field_inits}
        field_names = set(struct_info.fields.keys())
        matches_fields = provided_params == field_names
        matching_inits = []
        # An init matches when the provided named arguments are a subset of its
        # parameters and every omitted parameter carries a default value
        # (design 53). With no defaults this reduces to the exact-set match.
        def _init_matches(method_info):
            init_names = list(method_info.param_names)
            if not provided_params.issubset(set(init_names)):
                return False
            dv = method_info.default_values or []
            name_to_default = dict(zip(init_names, dv))
            return all(name_to_default.get(n) is not None
                       for n in init_names if n not in provided_params)
        # Check for init methods in both methods dict (legacy) and init_methods list (namespace)
        for method_name, method_info in struct_info.methods.items():
            if method_info.is_init and _init_matches(method_info):
                matching_inits.append(method_info)
        # Also check init_methods list (for StructSymbol from namespace)
        if hasattr(struct_info, 'init_methods'):
            for method_info in struct_info.init_methods:
                if _init_matches(method_info):
                    matching_inits.append(method_info)
        total_matches = (1 if matches_fields else 0) + len(matching_inits)
        if total_matches == 0:
            # Collect available init methods from both methods dict and init_methods list
            available_inits = [m.param_names for m in struct_info.methods.values() if m.is_init]
            if hasattr(struct_info, 'init_methods'):
                available_inits.extend([m.param_names for m in struct_info.init_methods])
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"no matching initializer for `{expr.struct_name}` with parameters: {', '.join(sorted(provided_params))}",
                expr.line, expr.column,
                hint=f"field init expects: {', '.join(sorted(field_names))}" +
                     (f"; available init methods: {available_inits}" if available_inits else "")
            )
            return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args, symbol=struct_info)
        elif total_matches > 1:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"ambiguous initializer for `{expr.struct_name}` - matches both field initialization and custom init",
                expr.line, expr.column,
                hint="use different parameter names in init method to disambiguate"
            )
            return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args, symbol=struct_info)
        if matches_fields:
            # Member visibility (design 80): memberwise struct-literal construction
            # cross-module requires ALL fields visible (else use a visible init).
            # Runs after the design-66 function-call reinterpretation above, so it
            # only fires for a genuine struct literal. (`_check_field_visible`
            # itself exempts a synthesized enclosing function.)
            for _fname in struct_info.field_order:
                self._check_field_visible(struct_info, _fname,
                                          expr.struct_name, expr)
            expr.resolved_init_params = None
            for field_name, field_value in expr.field_inits:
                declared_type = struct_info.fields[field_name]
                expected_type = declared_type
                if type_mapping:
                    expected_type = expected_type.substitute(type_mapping)
                actual_type = self._check_init_field_value(field_value, expected_type)
                if expected_type.kind == TypeKind.OPTIONAL and isinstance(field_value, NoneLiteral):
                    field_value.resolved_type = expected_type
                allow_wrap = self._df3_allow_wrap(
                    declared_type, set(type_mapping.keys()) if type_mapping else None)
                if actual_type and not self._arg_type_ok(field_value, actual_type, expected_type, allow_wrap):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"field `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column,
                        hint=self._int_conversion_hint(actual_type, expected_type)
                    )
                self._check_value_transfer(field_value, expected_type, "struct field",
                                           field_value.line, field_value.column)
        else:
            method_info = matching_inits[0]
            # Member visibility (design 80): gate a custom initializer cross-module.
            self._check_method_visible(expr.struct_name, "init", method_info, expr)
            # Design 53: fill omitted init parameters from their defaults by
            # appending them as named arguments, so the argument loop and codegen
            # see a complete set (evaluated per call, like an explicit argument).
            provided_now = {fn for fn, _ in expr.field_inits}
            _dv = method_info.default_values or []
            _n2d = dict(zip(method_info.param_names, _dv))
            for pname in method_info.param_names:
                if pname not in provided_now and _n2d.get(pname) is not None:
                    expr.field_inits.append((pname, _n2d[pname]))
            expr.resolved_init_params = method_info.param_names
            # design 24 item 3: a custom `init` runs user code — record the
            # suspend-graph edge to it.
            self._effect_call_method(
                method_info, f"`{expr.struct_name}.init`", expr.line)
            init_values = []
            init_param_types = []
            init_param_names = []
            for field_name, field_value in expr.field_inits:
                param_idx = method_info.param_names.index(field_name)
                declared_type = method_info.param_types[param_idx]
                expected_type = declared_type
                if type_mapping:
                    expected_type = expected_type.substitute(type_mapping)
                actual_type = self._check_init_field_value(field_value, expected_type)
                allow_wrap = self._df3_allow_wrap(
                    declared_type, set(type_mapping.keys()) if type_mapping else None)
                if actual_type and not self._arg_type_ok(field_value, actual_type, expected_type, allow_wrap):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"parameter `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column,
                        hint=self._int_conversion_hint(actual_type, expected_type)
                    )
                self._check_value_transfer(field_value, expected_type, "init argument",
                                           field_value.line, field_value.column)
                init_values.append(field_value)
                init_param_types.append(expected_type)
                init_param_names.append(field_name)
            self._check_call_exclusivity(init_values, init_param_types,
                                         param_names=init_param_names)
        built = SawType(TypeKind.STRUCT, struct_name=expr.struct_name,
                        type_args=expr.type_args, symbol=struct_info)
        return self._init_call_type(
            matching_inits[0] if not matches_fields else None,
            built, type_mapping)

    def _init_call_type(self, method_info, built, type_mapping=None):
        """The type a `T(args...)` CONSTRUCTION hands back — DF-245a.

        The receiver, unless the `init` that matched declares the fallible form,
        in which case it is that `Result<T, E>` and the construction composes
        with `try`/`try!`/`try?`/`match`, the routing clause and design 151's
        discard rule with nothing else written. `_init_declared_return` has
        already refused every other declared return, so there are only these
        two answers to pick between.

        TWO POSITIONS — the matrix this rule quantifies over, since a
        construction is written in exactly two ways:
          1. `_check_struct_init`        — the bare `T(...)`
          2. `_check_module_struct_init` — the qualified `mod.T(...)`
        A memberwise literal passes `None` here: it runs no `init` at all, so it
        can only ever build the receiver.
        """
        if method_info is None:
            return built
        declared = getattr(method_info, 'return_type', None)
        if declared is None or not declared.is_result():
            return built
        return declared.substitute(type_mapping) if type_mapping else declared

    def _check_none_literal(self, expr: NoneLiteral) -> Optional[SawType]:
        """Check None literal - returns a special 'None' type that can unify with any T?.

        Deliberately still the UNTYPED optional even when
        `_apply_literal_expected_type` has pushed an expectation down (DF-146l):
        the untyped form is what unifies with any `T?`, and returning the
        expectation here would make `_check_expression` stamp a concrete type on
        an absence — which, for a `UnsafePointer<T>?` field initialized to
        `None`, reads as the enclosing function NAMING a value of unsafe type
        under design 130's trigger rule. Writing `None` names no pointer. The
        expectation is consumed by codegen, which is the one place that needs a
        payload type to size the `{i1, T}` it builds.
        """
        return SawType(TypeKind.OPTIONAL, inner_type=None)

    def _propagate_optional_type(self, expr: Expression, expected_type: SawType):
        """THE CONTEXTUAL-`None` FUNNEL: push an expected optional type onto every
        bare `None` a value expression can hand out, so codegen can size the
        `{i1, T}` it builds.

        Runs AFTER the subexpression has been checked ("later contextual
        annotation wins"), which is what separates it from
        `_apply_literal_expected_type` — the other half of the same job, which
        runs BEFORE. Its ENTRY POINTS, every one of them a slot that names a type
        the `None` flowing into it has to adopt:
          1. `_check_function` / `_check_method`  — a body's TAIL at `-> T?`
          2. `_check_return_statement`            — `return None` at `-> T?`
          3. `_prepare_ok_payload`                — the Ok payload of a
             `Result<T?, E>`, at every one of `_autowrap_into_result`'s four
             entry points and at the DF-140d `return` branch above it
          4. `_check_let` / `_check_assignment`   — an annotated slot
          5. `_check_struct_init`                 — a field initializer
          6. `_check_nil_coalesce`                — a `??` default
          7. `_check_if_expr` / `_check_match_expr` (via `_annotate_none_in_block`)
             — the arm that has no type of its own, taking the other arm's
          8. `_check_closure`                     — a closure body's tail
          9. `_check_call` argument auto-wrap     — a `None` at a `T?` parameter

        TWO STAMPS, and the second is the DURABLE one (DF-245c). `resolved_type`
        is where codegen looks first, but it is also the field
        `_check_expression` stamps generically on every node it visits — so on
        the design-146 SECOND typecheck pass, over the post-transform AST, the
        generic `Optional<?>` overwrites whatever was pushed here. That is
        invisible in a single-pass compile and fatal once the coroutine
        transform runs: `return None` at a `-> Result<T?, E>` was rewritten into
        a `ResultOkWrap` by the first pass, so on the second pass the DF-140d
        branch that annotated it no longer matches, nothing re-annotates, and
        the `None` reaches codegen bare — in whatever function happens to
        contain it, whether or not any task calls it. `expected_type` is the
        field that survives (it is an ordinary annotation nothing re-derives),
        which is exactly why `_apply_literal_expected_type` case (0) chose it for
        the same value; stamping both keeps the same-pass reader working and
        makes the annotation outlive a re-check.
        """
        if expr is None:
            return
        if isinstance(expr, NoneLiteral):
            expr.resolved_type = expected_type
            if (expected_type is not None
                    and expected_type.kind == TypeKind.OPTIONAL
                    and expected_type.inner_type is not None):
                expr.expected_type = expected_type
        elif isinstance(expr, IfExpr):
            if expr.then_branch and expr.then_branch.final_expr:
                self._propagate_optional_type(expr.then_branch.final_expr, expected_type)
            if expr.else_branch and expr.else_branch.final_expr:
                self._propagate_optional_type(expr.else_branch.final_expr, expected_type)
        elif isinstance(expr, IfLetExpr):
            if expr.then_branch and expr.then_branch.final_expr:
                self._propagate_optional_type(expr.then_branch.final_expr, expected_type)
            if expr.else_branch and expr.else_branch.final_expr:
                self._propagate_optional_type(expr.else_branch.final_expr, expected_type)
        elif isinstance(expr, MatchExpr):
            for arm in expr.arms:
                body = arm.body
                if body is None:
                    continue
                # A match arm body is either a Block (propagate into its tail) or
                # a bare expression (propagate directly) — e.g. `case Occupied(k,v)
                # -> v` in an optional-returning function (design 48).
                if isinstance(body, Block):
                    if body.final_expr:
                        self._propagate_optional_type(body.final_expr, expected_type)
                else:
                    self._propagate_optional_type(body, expected_type)
        elif isinstance(expr, Block):
            if expr.final_expr:
                self._propagate_optional_type(expr.final_expr, expected_type)

    def _annotate_none_in_block(self, block: Block, resolved_type: SawType):
        """Annotate any NoneLiteral in the block's final expression with its resolved type."""
        if block.final_expr is not None:
            self._propagate_optional_type(block.final_expr, resolved_type)

    def _annotate_none_in_expr(self, expr: Expression, resolved_type: SawType):
        """Recursively find and annotate NoneLiteral nodes with their resolved type."""
        self._propagate_optional_type(expr, resolved_type)

    def _check_force_unwrap(self, expr: ForceUnwrap) -> Optional[SawType]:
        """Check force unwrap: expr! - unwraps T? to T."""
        inner_type = self._check_expression(expr.expr)
        if inner_type is None:
            return None
        if inner_type.kind == TypeKind.STRUCT and self.get_type_alias_info(inner_type.struct_name):
            underlying = self._get_underlying_type(inner_type)
            if underlying.kind == TypeKind.OPTIONAL:
                return underlying.inner_type
        if inner_type.kind != TypeKind.OPTIONAL:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot force unwrap non-optional type `{inner_type}`",
                expr.line, expr.column
            )
            return inner_type
        return inner_type.inner_type

    def _check_optional_take(self, expr: MethodCall,
                             opt_type: SawType) -> Optional[SawType]:
        """Check `o.take()` — `Optional.take(&var self) -> T?` (design 131).

        The runtime consuming read: it writes `None` into the place and returns
        what was there, owned. Because the write is a real store rather than a
        static retirement, it reaches places `move` cannot — above all a struct
        FIELD, where no-partial-moves forbids `move h.s` and design 131's
        `move h.s!` with it.

        Checked like any `&var self` method: the receiver must be a mutable
        place, and its path joins the enclosing call's exclusivity entries.
        """
        if expr.arguments:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`take()` takes no arguments, got {len(expr.arguments)}",
                expr.line, expr.column
            )
            return None
        if not self._is_lvalue(expr.object):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`take()` needs a place to write `None` back into",
                expr.line, expr.column,
                hint="call it on a variable, field, or element — the payload of "
                     "a temporary is already yours, so read it with `!`"
            )
            return None
        imm_root = self._immutable_receiver_root(expr.object)
        if imm_root is not None:
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                f"cannot call `take()` on immutable variable `{imm_root}`: "
                f"it writes `None` back into the place",
                expr.line, expr.column,
                hint="consider using `var` instead of `let` to make it mutable",
            )
        # design 188 unit 4: `take()` moves the payload OUT of the place, which
        # is a relocation whatever the spelling.
        payload = opt_type.inner_type if opt_type is not None else None
        if self._is_no_move_type(payload):
            self._error(
                ErrorKind.CANNOT_COPY,
                f"cannot `take()` a `{payload}` payload: it is `NoMove`, so it "
                f"lives where its constructor built it and may not be moved out "
                f"of the optional." + self._no_move_scope_note(payload),
                expr.line, expr.column,
                hint="reach the payload through a borrow (`o!.method()`), or "
                     "keep the value in the binding it was built in"
            )
            return None
        # Mark for codegen and for the enclosing call's exclusivity sweep: a
        # by-value argument that TAKES is a mutable access to its receiver path.
        expr.optional_take = True
        self._check_call_exclusivity([], [], receiver=expr.object,
                                     receiver_mutable=True)
        return opt_type

    def _check_optional_presence(self, expr: MethodCall,
                                 opt_type: SawType) -> Optional[SawType]:
        """Check `o.is_some()` / `o.is_none()` — `Optional`'s tag-only reads.

        An optional is a tag beside a payload, and these two answer the tag.
        Nothing is taken out, so there is no transfer to judge: design 131's
        copy-tier table is never consulted and the answer is the same for a
        `NoCopy` payload as for an `Int`. That tier-independence is the point —
        it is what lets a move-only payload be asked whether it is there, which
        `if let _ = …` could not do at every position (DF-218a).

        `&self`-shaped, so unlike `take` it needs no mutable place and no place
        at all: a call result is as good a receiver as a local. The receiver's
        path joins the enclosing call's exclusivity entries as a SHARED access,
        which is what lets a presence test sit beside other readers.
        """
        if expr.arguments:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{expr.method_name}()` takes no arguments, "
                f"got {len(expr.arguments)}",
                expr.line, expr.column
            )
            return None
        expr.optional_presence = expr.method_name
        self._check_call_exclusivity([], [], receiver=expr.object,
                                     receiver_mutable=False)
        return SawType(TypeKind.BOOL)

    def _check_nil_coalesce(self, expr: NilCoalesce) -> Optional[SawType]:
        """Check nil coalescing: expr ?? default - returns T."""
        opt_type = self._check_expression(expr.expr)
        default_type = self._check_expression(expr.default)
        if opt_type is None or default_type is None:
            return default_type
        if opt_type.kind != TypeKind.OPTIONAL:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"left side of `??` must be optional, got `{opt_type}`",
                expr.line, expr.column
            )
            return opt_type
        # design 195 rule 1's carve-out, at the `??` default: a BARE integer
        # literal adopts the PAYLOAD's type, exactly as an operator's literal
        # operand adopts the other operand's. `??` merges two positions into one
        # value, so its two operands are peers in the same sense.
        #
        # Without it the whole expression took the LITERAL's platform `Int`:
        # `elf.u8_at(off) ?? 0` on a `UInt?` typed `Int`, so a comparison one
        # line down met an `Int` and a `UInt` and the agreement rule refused a
        # program whose author had written nothing mixed (blade's ELF reader).
        adopted = self._adopt_bare_literal_into(expr.default, opt_type.inner_type)
        if adopted is not None:
            default_type = adopted
        # DF-146l site 2: a bare `None` on the RHS is a `None` of the LHS's
        # PAYLOAD type. `m["x"] ?? None` on a `Map<String, Int?>` has an `Int??`
        # left operand, so the default is an `Int?` — the one shape where the
        # RHS of `??` is itself an optional and the literal has nowhere else to
        # learn that from. Without the stamp it reached codegen untyped, and the
        # expression's own result type came back as the untyped optional too.
        if (default_type.is_none_literal() and opt_type.inner_type is not None
                and self._resolve_type_alias(opt_type.inner_type).is_optional()):
            self._propagate_optional_type(expr.default, opt_type.inner_type)
            default_type = opt_type.inner_type
        # design 228 leg 6: a DIVERGING default satisfies any expected type, the
        # way a diverging expression does in every other value position.
        # `_types_compatible`'s bottom-type escape only fires in the SOURCE
        # slot, and the compatibility check below reads the other way round
        # (payload into default), so the diverging operand sat in the TARGET
        # slot where nothing looked for it: `o ?? panic("gone")` — and
        # `o ?? fault(p)` for any `-> Never` callee — was refused with
        # ``optional inner type `Int` does not match default type `Never` ``.
        # The expression can only ever yield the payload, so that is its type.
        if (default_type.kind == TypeKind.NEVER
                and opt_type.inner_type is not None):
            self._check_payload_read(expr.expr, opt_type.inner_type, expr,
                                     "the result of `??`", expr.line, expr.column)
            return opt_type.inner_type
        # DF-174h: `??` PEELS one optional layer, so the default owes the PEELED
        # type. The compatibility check below reads the other way round — it asks
        # whether the payload could flow into the DEFAULT — and `T` flowing into
        # `T?` is exactly the auto-wrap rule, so a default one layer too deep
        # sailed through it. `v.get(9) ?? v.get(0)` on a `Vector<Int?>` has two
        # `Int??` operands and should be a clean error; instead the mis-typed
        # default reached codegen, where it silently took the absent path (and,
        # in the peeled-twice spelling, could not be indexed at all). Depth is
        # the one part the wrap rule must not paper over.
        if (opt_type.inner_type is not None and default_type is not None
                and not default_type.is_none_literal()
                and self._optional_depth(default_type)
                > self._optional_depth(opt_type.inner_type)):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`??` peels one optional layer, so the default owes "
                f"`{opt_type.inner_type}`, but this default is `{default_type}`",
                expr.default.line, expr.default.column,
                hint="peel the default too, or bind the outer layer with "
                     "`if let` before coalescing"
            )
            return opt_type.inner_type
        # design 205: an INTEGER pair is design 195 rule 2's business — the merge
        # below owns the lossless-widening admission and the refusal.
        if (opt_type.inner_type
                and not self._both_int_kinds(opt_type.inner_type, default_type)
                and not self._types_compatible(opt_type.inner_type, default_type)):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"optional inner type `{opt_type.inner_type}` does not match default type `{default_type}`",
                expr.line, expr.column
            )
        # design 131: `a ?? b` always yields an owned value, so BOTH arms are
        # transfers. The left arm extracts a payload out of `a` and takes the
        # place rule; the right arm is an ordinary transfer that had never been
        # checkpointed at all — so `let s = opt ?? other` used to alias `other`
        # and double-free it.
        self._check_payload_read(expr.expr, opt_type.inner_type, expr,
                                 "the result of `??`", expr.line, expr.column)
        self._check_value_transfer(expr.default, opt_type.inner_type,
                                   "the default operand of `??`",
                                   expr.default.line, expr.default.column)
        # design 195 rule 2: the payload and the default merge into one value, so
        # they take the same widening rule the `if` and `match` arms take. The
        # DEFAULT is widened here with a synthesized `as`; the payload has no AST
        # node of its own (it is an `extractvalue` out of the optional), so its
        # half is `_generate_nil_coalesce`'s.
        #
        # This is also what fixes the RESULT type: the method used to answer with
        # the default's type whatever the payload's was, so `o ?? -7i16` on an
        # `Int?` typed `Int16` while codegen phi'd at the payload's width.
        merged = self._merge_value_branch_types(
            [opt_type.inner_type, default_type],
            "the `??` payload and its default", expr.line, expr.column)
        if merged is not None:
            expr.default = self._widened(expr.default, merged)
            return merged
        return default_type

    def _check_optional_chain(self, expr: OptionalChain) -> Optional[SawType]:
        """Check optional chaining: expr?.member - returns U?."""
        opt_type = self._check_expression(expr.expr)
        if opt_type is None:
            return None
        if opt_type.kind != TypeKind.OPTIONAL:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot use optional chaining on non-optional type `{opt_type}`",
                expr.line, expr.column
            )
            return None
        inner_type = opt_type.inner_type
        if inner_type is None:
            return None
        if inner_type.kind != TypeKind.STRUCT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access member of non-struct type `{inner_type}`",
                expr.line, expr.column
            )
            return None
        struct_info = self.get_struct_info(inner_type.struct_name)
        if struct_info is None:
            return None
        if expr.member not in struct_info.fields:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{inner_type.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=f"available fields: {', '.join(struct_info.field_order)}"
            )
            return None
        field_type = struct_info.fields[expr.member]
        return SawType(TypeKind.OPTIONAL, inner_type=field_type)

    # ------------------------------------------------------------------ #
    # Design 111 — full optional chaining. A `?.` hop is a BindOptional node
    # (unwrap-or-short-circuit); the maximal postfix run is an OptionalEvalExpr
    # (flatten to `U?`); `x?.y = v` is an OptionalChainAssign (`Void?`).
    # ------------------------------------------------------------------ #
    def _check_bind_optional(self, expr: BindOptional) -> Optional[SawType]:
        """A `?.` unwrap point: the receiver must be `Optional<U>`; the hop yields
        the payload `U` (the object the following segment projects/calls). `None`
        short-circuits the enclosing chain at codegen — here it is a pure type
        projection."""
        opt_type = self._check_expression(expr.expr)
        if opt_type is None:
            return None
        if opt_type.kind != TypeKind.OPTIONAL:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot use optional chaining on non-optional type `{opt_type}`",
                expr.line, expr.column
            )
            return None
        inner_type = opt_type.inner_type
        if inner_type is None:
            return None
        return self._resolve_type(inner_type)

    def _check_optional_eval(self, expr: OptionalEvalExpr) -> Optional[SawType]:
        """The whole optional chain. Type the spine, then flatten to `U?` — an
        already-optional final segment stays `U?`, never `U??`. A final FIELD
        projection copies its value, so it must be freely copyable; a final METHOD
        result is a fresh owned value and is unrestricted."""
        inner_type = self._check_expression(expr.expr)
        if inner_type is None:
            return None
        if isinstance(expr.expr, MemberAccess):
            self._check_chain_final_field_copyable(expr.expr, inner_type)
        if inner_type.kind == TypeKind.OPTIONAL:
            return inner_type
        return SawType(TypeKind.OPTIONAL, inner_type=inner_type)

    def _check_chain_final_field_copyable(self, member: MemberAccess,
                                          field_type: SawType) -> None:
        """A final `?...field` projection reads the field out BY VALUE (there is no
        `.copy()`/`move` spelling inside a chain), so the field must be freely
        copyable — trivially copyable or Copy. A move-only field (NoCopy,
        an owning Deinit type, or ExplicitCopy) is rejected (matching
        `Vector.get`'s copyable-element rule)."""
        if self._chain_field_freely_copyable(field_type):
            return
        detail = "ExplicitCopy" if self._is_explicit_copy_type(field_type) \
            else "move-only (NoCopy / owns a resource)"
        self._error(
            ErrorKind.CANNOT_COPY,
            f"cannot project field `{member.member}` of type `{field_type}` "
            f"through an optional chain: it is {detail}, and a chain projection "
            f"copies the value by value",
            member.line, member.column,
            hint="bind the optional first (`if let x = opt`) and move/`.copy()` "
                 "the field out, or end the chain in a method that returns a value")

    def _chain_field_freely_copyable(self, t: SawType) -> bool:
        """Whether a final-projection field type can be read out by value with no
        `move`/`.copy()` — trivially copyable or Copy at the leaves,
        recursing through Optional / tuple / array wrappers (so an `Optional<Point>`
        or `String?` final field is fine, an owning/NoCopy/ExplicitCopy one is
        not)."""
        if t is None:
            return True
        t = self._resolve_type_alias(t)
        if t.kind == TypeKind.OPTIONAL:
            return self._chain_field_freely_copyable(t.inner_type)
        if t.kind == TypeKind.TUPLE:
            return all(self._chain_field_freely_copyable(e)
                       for e in (t.element_types or []))
        if t.kind == TypeKind.ARRAY:
            return self._chain_field_freely_copyable(t.array_element_type)
        if self._is_no_copy_type(t) or self._is_explicit_copy_type(t):
            return False
        if self._is_implicit_copy_type(t):
            return True
        return self._is_trivially_copyable(t)

    def _check_optional_chain_assign(self, expr: OptionalChainAssign) -> Optional[SawType]:
        """`x?.y = v` (design 111) and `x?.y += v` (design 227 unit 4). Writes
        the RHS through the chain into the payload FIELD in place iff every
        optional hop is non-None; the RHS is skipped entirely on short-circuit
        (codegen). Types to `Void?` — `None` = skipped, `Some(unit)` = written.

        The compound spelling reads the field and applies the operator on the
        written path only, so it takes the operand rules of the compound
        STATEMENT (`_check_compound_operands`) where the plain one takes the
        assignment transfer rules."""
        target = expr.target
        if not isinstance(target, OptionalEvalExpr):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "the left-hand side of this assignment is not an optional chain",
                expr.line, expr.column)
            return None
        spine = target.expr
        if not isinstance(spine, MemberAccess):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "an optional-chain assignment must target a field of the payload "
                "(the final segment must be `.field`, not a method call)",
                expr.line, expr.column)
            return None
        # Type the target field (also type-checks + stamps the whole chain, and
        # verifies the field exists and is visible for writing).
        field_type = self._check_expression(spine)
        if field_type is None:
            return None
        # design 227: a chain assignment is a WRITE, so it takes the write-target
        # funnel like every other one — which is how DF-225k closed. `self.c?.n
        # = 99` in a `&self` method used to reach nothing at all: the head check
        # below defers a `self` root to "governed by `&var self`", and until the
        # funnel was here nothing downstream governed it, so the write landed in
        # the receiver's copy and vanished.
        #
        # `immutable_root=False` — design 111's `_check_chain_assign_head_mutable`
        # owns that question here, with a diagnostic that names the chain.
        # Exclusivity DOES come from the funnel, moves included: a chain writes
        # THROUGH a payload it does not revive.
        root_path = self._build_access_path(spine)
        self._check_write_target(spine, expr.line, expr.column,
                                 compound=getattr(expr, 'op', None) is not None,
                                 value=expr.value, node=expr, rhs_moves=True,
                                 rhs_what="this optional-chain assignment",
                                 immutable_root=False)
        # Mutability: the chain head must be a mutable place (a `var` or a
        # `&var`-reachable path).
        self._check_chain_assign_head_mutable(spine, root_path, expr)
        chain_op = getattr(expr, 'op', None)
        if chain_op is not None:
            # `x?.y += v` — the field is read and written, so the value side is
            # the compound statement's, not the assignment's. A bare RHS literal
            # adopts the FIELD's fixed-width type first (design 87).
            self._apply_literal_expected_type(expr.value, field_type)
            value_type = self._check_expression(expr.value)
            if value_type is not None:
                self._check_compound_operands(spine, expr.value, field_type,
                                              value_type, chain_op,
                                              expr.line, expr.column)
            return SawType(TypeKind.OPTIONAL, inner_type=SawType(TypeKind.VOID))
        # RHS follows ordinary assignment transfer rules against the field type,
        # including optional-None propagation onto a bare `None` RHS.
        value_type = self._check_expression(expr.value)
        field_resolved = self._resolve_type_alias(field_type)
        if (value_type and value_type.is_none_literal()
                and field_resolved.is_optional()):
            self._propagate_optional_type(expr.value, field_resolved)
            value_type = field_resolved
        if value_type and not self._transfer_compatible(value_type, field_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot assign `{value_type}` to field of type `{field_type}`",
                expr.line, expr.column,
                hint=self._int_conversion_hint(value_type, field_type))
        self._check_value_transfer(expr.value, field_type,
                                   "optional-chain assignment",
                                   expr.line, expr.column)
        return SawType(TypeKind.OPTIONAL, inner_type=SawType(TypeKind.VOID))

    def _chain_assign_root(self, spine):
        """Walk a chain-assignment target to its ROOT node, transparent through
        MemberAccess/BindOptional/OptionalEvalExpr/tuple/index projections."""
        node = spine
        while True:
            if isinstance(node, MemberAccess):
                node = node.object
            elif isinstance(node, (BindOptional, OptionalEvalExpr)):
                node = node.expr
            elif isinstance(node, TupleIndex):
                node = node.tuple_expr
            elif isinstance(node, ArrayIndex):
                node = node.array_expr
            elif (isinstance(node, MethodCall)
                  and getattr(node, 'place_struct', None) is not None):
                # A NAMED borrows accessor is a projection like any other
                # (DF-175d): `v.get(0)?.value = x` names storage `v` holds, so
                # the mutability question is `v`'s. The subscript spelling of the
                # same lend walked through as an ArrayIndex and this one did not,
                # which is the whole of why one worked and the other did not.
                node = node.object
            else:
                return node

    def _check_chain_assign_head_mutable(self, spine, root_path, expr) -> None:
        """The head of a chain assignment must be an assignable, mutable place."""
        root = self._chain_assign_root(spine)
        if isinstance(root, SelfExpr):
            return  # governed by `&var self`, like an ordinary field write
        if not isinstance(root, Identifier):
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                "the head of an optional-chain assignment must be a mutable "
                "variable or a `&var`-reachable path",
                expr.line, expr.column)
            return
        root_static = (self.namespace.get_static(root.name,
                                                 self._accessor_vis_module())
                       if self.current_scope.lookup(root.name) is None else None)
        if root_static is not None and not getattr(root_static, 'is_var', False):
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                f"cannot assign through optional chain rooted at the immutable "
                f"static `{root.name}`",
                expr.line, expr.column)
            return
        info = self.current_scope.lookup(root.name)
        if info is None:
            return
        if info.mutable:
            return
        # A `&var` reference param is a mutable path; a `&` or plain `let` is not.
        if (info.type is not None and info.type.kind == TypeKind.REFERENCE
                and info.type.reference_mutable):
            return
        self._error(
            ErrorKind.IMMUTABLE_ASSIGNMENT,
            f"cannot assign through optional chain: `{root.name}` is not mutable",
            expr.line, expr.column,
            hint="consider using `var` instead of `let` to make it mutable")

    def _check_write_rhs_exclusivity(self, root_path, value, expr,
                                     what: str, moves: bool = True) -> None:
        """Law of Exclusivity on a WRITTEN path: the statement writes the root,
        so its right-hand side may not also borrow (`&`/`&var`) or `move` an
        overlapping path.

        Question 5 of `_check_write_target` (design 227), and reached ONLY
        through it — which is the point. It used to have two callers of its own,
        an optional-chain assignment (design 111) and a plain assignment (design
        193 unit 4), and `p.x = f(&var p)` compiled while `p?.x = f(&var p)` was
        refused, making the rule a property of the SPELLING rather than of the
        write: the callee's mutations to `p` are made and then clobbered by the
        assignment that follows, the same lost write design 188 refused between
        two windows. Design 193 unified those two and left a THIRD spelling
        unasked — `p.x += f(&var p)` (DF-225i), whose overlap is worse still,
        since a compound assignment reads the target as well as writing it.

        `moves` is the one thing the entry points disagree about, and the
        funnel's callers pass it. An assignment (plain or compound) REVIVES its
        target (design 15 rule 3), so `acc = combine(move acc, move elem)` —
        std `Vector.fold`, and the accumulator idiom generally — hands ownership
        to the callee and takes a fresh value back with no aliasing in it, and
        moving a root then writing a FIELD of it is a different statement that
        is already a use-after-move. A CHAIN assignment writes through a payload
        it does not revive, so that entry point asks about moves too.

        On `ast_walk.child_nodes` (design 193 unit 3). The hand-rolled walk this
        replaced descended a list's direct node items but stepped over TUPLES,
        which is the shape of `StructInit.field_inits` — so
        `p?.f = Foo(a: move x)` was invisible to the Law. It also walked
        `dataclasses.fields`, i.e. the cross-pass ANNOTATIONS as well as the
        tree; `structural_fields` (which `child_nodes` uses) leaves those out,
        so the check can no longer reach a node through a checker back-reference
        and judge the same borrow twice.
        """
        if root_path is None:
            return
        stack = [value]
        # `id()` is correct here and is NOT the identity design 126 R2 removed:
        # this is a within-one-traversal cycle guard over physical objects, it
        # never outlives the call, and it must treat two equal-but-distinct nodes
        # as distinct.
        seen = set()
        while stack:
            cur = stack.pop()
            if cur is None or id(cur) in seen:
                continue
            seen.add(id(cur))
            if isinstance(cur, ClosureExpr):
                continue  # a closure's captures are its own access domain
            other = None
            if isinstance(cur, ReferenceExpr):
                other = self._build_access_path(cur.expr)
            elif moves and isinstance(cur, MoveExpr):
                other = (cur.variable, ())
            if other is not None and self._paths_overlap(root_path, other):
                self._error(
                    ErrorKind.EXCLUSIVITY_VIOLATION,
                    f"exclusive access violation: `{root_path[0]}` is written by "
                    f"{what} while also being accessed in the right-hand side",
                    expr.line, expr.column,
                    hint="the right-hand side is evaluated first, so its writes "
                         "through that borrow are overwritten by this "
                         "assignment. Bind the value in its own statement, or "
                         "borrow a disjoint path")
                return
            stack.extend(child_nodes(cur))

    def _make_specialization_key(self, type_args: List[SawType]) -> tuple:
        """The shared definition — see `ast_nodes.specialization_key`. This was
        the diverged copy (DF-190c): it dropped a design-148 const-value
        argument to an empty key while codegen tagged it, so front and back
        would have disagreed about which specialized methods exist."""
        return specialization_key(type_args)

    def _name_to_type(self, name: str) -> SawType:
        """Convert a type name string to a SawType."""
        type_mapping = {
            'Int': SawType(TypeKind.INT),
            'UInt': SawType(TypeKind.UINT),
            'Float': SawType(TypeKind.FLOAT),
            'Bool': SawType(TypeKind.BOOL),
            'String': SawType(TypeKind.STRING),
            'Int8': SawType(TypeKind.INT8),
            'Int16': SawType(TypeKind.INT16),
            'Int32': SawType(TypeKind.INT32),
            'Int64': SawType(TypeKind.INT64),
            'UInt8': SawType(TypeKind.UINT8),
            'UInt16': SawType(TypeKind.UINT16),
            'UInt32': SawType(TypeKind.UINT32),
            'UInt64': SawType(TypeKind.UINT64),
        }
        if name in type_mapping:
            return type_mapping[name]
        # Check if it's a user-defined struct
        struct_info = self.namespace.lookup_struct(name)
        if struct_info:
            return SawType(TypeKind.STRUCT,
                           struct_name=self._sym_identity(struct_info, name),
                           symbol=struct_info)
        # Check if it's an enum
        enum_info = self.namespace.lookup_enum(name)
        if enum_info:
            return SawType(TypeKind.ENUM,
                           enum_name=self._sym_identity(enum_info, name),
                           symbol=enum_info)
        # Fallback to STRUCT type
        return SawType(TypeKind.STRUCT, struct_name=name)

    def _lookup_method(self, struct_info, method_name: str, type_args: List[SawType] = None):
        """Look up a method, checking specialized extensions first.

        Extension scoping (design 142): a method whose defining module is out of
        scope here does not exist here. What a file can see is its own
        extensions, its direct imports', and the receiver type's own — never a
        transitive dependency's."""
        # First, check if there's a specialized extension matching the type args
        if type_args and struct_info.specialized_methods:
            spec_key = self._make_specialization_key(type_args)
            if spec_key in struct_info.specialized_methods:
                specialized = struct_info.specialized_methods[spec_key]
                sm = specialized.get(method_name)
                if sm is not None and self._ext_scope_allows(sm, struct_info):
                    return sm

        # Fall back to generic methods
        m = struct_info.methods.get(method_name)
        if m is not None:
            if self._ext_scope_allows(m, struct_info):
                return m
            # `methods` keeps the FIRST-registered overload as the
            # representative, and registration order follows the topological
            # module order — so an out-of-scope module's extension can occupy the
            # slot while this file's own is right behind it in the overload list.
            for cand in struct_info.method_overloads.get(method_name, []):
                if self._ext_scope_allows(cand, struct_info):
                    return cand

        return None

    def _receiver_method_overloads(self, struct_info, method_name: str) -> List:
        """THE overload set of a RESOLVED receiver, in scope here (design 256).

        Keyed on the receiver's design-144 IDENTITY — the resolved symbol
        itself — never on the spelling the source happened to write. This
        replaced a `Namespace.lookup_method_overloads(struct_name, …)` that
        re-resolved the set by WRITTEN NAME while its sibling `_lookup_method`
        read the same tables off the symbol the call had already resolved. Every
        way of naming a receiver whose type name is not bound as a simple name
        HERE missed in that lookup — a module QUALIFIER (`pc_leaf.Panel`), a
        value whose type the file never spells (`import dep.{hand}`) — the set
        came back EMPTY, and the call collapsed onto whichever overload
        registered first (DF-280a, three faces).

        ENTRY POINTS, all of them:
          * `_instance_method_alternative` — DF-217q's static-vs-instance
            disambiguation.
          * the instance call's design-55 resolver and the design-142 call-site
            ambiguity check, both in `_check_instance_method_call`.
          * `_static_method_overloads`, which is the STATIC side's own funnel:
            the bare `Bag.make(...)` / `Tone.of(...)` routes and the qualified
            `mod.Bag.make(...)` / `mod.Tone.of(...)` ones.
        `_out_of_scope_method_modules` is the COMPLEMENT (the modules a
        candidate was filtered OUT for) and reads the same tables inverted; it
        is not a consumer of this list.

        Filtering is design 142's scope predicate and nothing else — which
        candidates EXIST here, never whether their visibility permits the
        access (`_check_method_visible` still asks that). `methods` keeps the
        first-registered overload as a representative and is always also in
        `method_overloads`; the union is the belt-and-braces
        `_out_of_scope_method_modules` uses for the same reason."""
        candidates = list(struct_info.method_overloads.get(method_name, []))
        rep = struct_info.methods.get(method_name)
        if rep is not None and rep not in candidates:
            candidates.append(rep)
        return [s for s in candidates if self._ext_scope_allows(s, struct_info)]

    def _static_method_overloads(self, struct_info, method_name: str) -> List:
        """The STATIC overloads of a resolved receiver TYPE (design 256).

        The static routes used to read `struct_info.methods[name]` — the lone
        representative — or re-resolve by written name; the qualified one
        consulted no set AT ALL, which is why `mod.Bag.make(from:, bump:)` was
        ``has no parameter named `from` `` while the bare spelling resolved.
        An instance overload sharing the name is not a candidate here (DF-217q's
        rule, read the other way)."""
        return [s for s in self._receiver_method_overloads(
                    struct_info, method_name)
                if getattr(s, 'is_static', False)]

    def _instance_method_alternative(self, struct_info, method_name: str):
        """An INSTANCE method of this name, when the representative the lookup
        returned was a static one (DF-217q).

        `struct_info.methods` keeps the first-registered overload as the
        representative, so a type carrying both `Bag.make(...)` and
        `b.make(...)` can hand a static back to an instance call site. That is
        an overload-set question, not a refusal: only when NO instance overload
        of the name is visible here does the call have nothing to mean."""
        for cand in self._receiver_method_overloads(struct_info, method_name):
            if not getattr(cand, 'is_static', False):
                return cand
        return None

    def _out_of_scope_method_modules(self, struct_info, method_name: str,
                                     type_args: List[SawType] = None) -> List[str]:
        """The modules that define `method_name` on this type but are not in
        scope here (design 142) — what the "no method" diagnostic names so the
        reader learns which import to add rather than concluding the method does
        not exist."""
        candidates = list(struct_info.method_overloads.get(method_name, []))
        m = struct_info.methods.get(method_name)
        if m is not None and m not in candidates:
            candidates.append(m)
        if type_args and struct_info.specialized_methods:
            spec_key = self._make_specialization_key(type_args)
            spec = struct_info.specialized_methods.get(spec_key) or {}
            if method_name in spec:
                candidates.append(spec[method_name])
        labels = []
        for sym in candidates:
            if self._ext_scope_allows(sym, struct_info):
                continue
            label = self._module_label(getattr(sym, 'def_module', ()) or ())
            if label not in labels:
                labels.append(label)
        return sorted(labels)

    def _first_cross_module_method_clash(self, overloads):
        """Two in-scope extension methods from DIFFERENT modules that no
        tie-break rule could separate (design 142).

        Declaring both is legal — neither module need know the other exists, and
        under the old global registry the loser was simply shadowed. It is the
        call site that cannot choose, so that is where the error belongs, naming
        both defining modules."""
        shaped = []
        for sym in overloads:
            off = 0 if sym.is_init else 1
            shaped.append((sym, self._overload_shape_keys(
                sym.param_types[off:], sym.type_params,
                (sym.default_values[off:] if sym.default_values else []),
                sym.param_names[off:])))
        for i in range(len(shaped)):
            for j in range(i + 1, len(shaped)):
                a, keys_a = shaped[i]
                b, keys_b = shaped[j]
                if not (keys_a & keys_b):
                    continue
                if (getattr(a, 'def_module', ()) or ()) != (getattr(b, 'def_module', ()) or ()):
                    return (a, b)
        return None

    # Generic bounds that grant `.copy()` in an abstract generic body.
    _COPY_BOUND_NAMES = frozenset({"Copy", "ExplicitCopy"})

    # The two Copy-family questions, kept apart at the ABSTRACT side exactly as
    # `Namespace` keeps them apart for concrete types (design 219).
    #
    # SILENT — bounds proving the parameter is on the merged `Copy` tier, so a
    # body may duplicate it with nothing written. `ExplicitCopy` is NOT one:
    # admitting it here is what let a ceremony-tier argument into a silently
    # copying body (S1 row 9d).
    _SILENT_COPY_BOUND_NAMES = frozenset({"Copy"})

    def _bound_satisfied(self, concrete: SawType, bound: str) -> bool:
        """Whether `concrete` satisfies a single type-param `bound`.

        Concrete types defer to the shared namespace helper (so the typechecker
        and codegen agree). An *abstract* type parameter still in scope is
        satisfied only by its own declared bounds: inside a generic body we
        cannot resolve it structurally, so `Vector<K>.copy()` is legal exactly
        when `K` itself carries a bound that proves it.

        The Copy family is the one place a bound is satisfied by a DIFFERENT
        bound: the merged `Copy` tier answers to either of its two spellings,
        and `ExplicitCopy` — the wider duplicable family — answers to any of the
        three, because a silently copyable parameter is duplicable too.
        """
        type_params = getattr(self, 'current_type_params', {})
        if concrete.kind == TypeKind.STRUCT and concrete.struct_name in type_params:
            param_bounds = type_params.get(concrete.struct_name) or []
            if bound in param_bounds:
                return True
            if bound in self._SILENT_COPY_BOUND_NAMES:
                return any(b in self._SILENT_COPY_BOUND_NAMES for b in param_bounds)
            if bound == "ExplicitCopy":
                return any(b in self._COPY_BOUND_NAMES for b in param_bounds)
            return False
        return self.namespace.type_satisfies_bound(concrete, bound)

    def _unmet_extension_bound(self, method_info, type_subst):
        """If a bounded-extension method is unavailable for this instantiation,
        return the first unmet (param_name, bound, concrete_type); else None.
        """
        bounds = getattr(method_info, 'extension_bounds', None)
        if not bounds:
            return None
        for param_name, param_bounds in bounds.items():
            concrete = type_subst.get(param_name)
            if concrete is None:
                continue
            for bound in param_bounds:
                if not self._bound_satisfied(concrete, bound):
                    return (param_name, bound, concrete)
        return None

    def _check_copy_call(self, expr: MethodCall, obj_type: SawType):
        """Handle a `.copy()` receiver. Returns (handled, result_type).

        handled=False means the receiver has a real copy() method
        (Copy/ExplicitCopy) and normal method dispatch should proceed.
        handled=True means this call was fully resolved here (trivial auto-Copy,
        a `T: Copy`-family bound, or a diagnostic on a non-Copy receiver).
        """
        type_params = getattr(self, 'current_type_params', {})

        # design 219 wave C (DF-217q): THE `.copy()`-needs-a-bound funnel, over
        # every receiver shape. The gate below used to be the whole rule and it
        # matched a BARE `T` only, so `(T, Int)`, `T?` and `[T; N]` reached
        # their own wrapper arms — each of which reasons about the wrapper and
        # not the parameter — and compiled unbounded.
        #
        # Gated on the ABSTRACT tier, which is true exactly when the answer
        # depends on the type argument: a receiver that declares its own copy
        # policy still answers for itself further down.
        if self.namespace.copy_tier(obj_type) == 'abstract':
            unbounded = self._tier_unbounded_copy_params(obj_type)
            if unbounded:
                name = unbounded[0]
                what = (f"type parameter `{name}`"
                        if obj_type.kind == TypeKind.STRUCT
                        and obj_type.struct_name == name
                        else f"`{obj_type}`, whose copy reaches the unbounded "
                             f"type parameter `{name}`")
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"cannot call `.copy()` on a value of unbounded {what}",
                    expr.line, expr.column,
                    hint=f"add the bound that says a copy exists: "
                         f"`<{name}: ExplicitCopy>` for the whole duplicable "
                         f"family, or `<{name}: Copy>` for the silent tier. "
                         f"Without one, `.copy()` here would be a real copy for "
                         f"some instantiations and a double free for others"
                )
                return True, None

        # Receiver is an opaque generic type parameter: allow .copy() only under
        # a Copy-family bound; the result is the type parameter itself.
        if obj_type.kind == TypeKind.STRUCT and obj_type.struct_name in type_params:
            bounds = type_params.get(obj_type.struct_name) or []
            if any(b in self._COPY_BOUND_NAMES for b in bounds):
                expr.resolved_type = obj_type
                return True, obj_type
            self._error(
                ErrorKind.CANNOT_COPY,
                f"cannot call `.copy()` on value of unbounded type parameter `{obj_type.struct_name}`",
                expr.line, expr.column,
                hint=f"add a `Copy` bound: `<{obj_type.struct_name}: Copy>`"
            )
            return True, None

        # Concrete type carrying a real copy() method (declared via a copy trait
        # or an ordinary user method): fall through to normal method dispatch.
        if obj_type.kind == TypeKind.STRUCT:
            struct_info = self.get_struct_info(obj_type.struct_name, from_type=obj_type)
            if struct_info and self._lookup_method(struct_info, "copy", obj_type.type_args) is not None:
                return False, None
        elif obj_type.kind == TypeKind.STRING:
            struct_info = self.get_struct_info("String")
            if struct_info and self._lookup_method(struct_info, "copy") is not None:
                return False, None

        # Trivially copyable (POD / primitive): .copy() is a bitwise copy.
        if self._is_trivially_copyable(obj_type):
            expr.resolved_type = obj_type
            return True, obj_type

        # A fixed array `[T; N]` is copyable iff its element type is (design 33).
        # `.copy()` duplicates it per element in index order; the result has the
        # same array type. (`[trivial; N]` was already handled above.)
        if obj_type.kind == TypeKind.ARRAY:
            # The DUPLICABLE family, not the silent tier (design 219's predicate
            # split): `.copy()` asks whether a copy EXISTS, which an ExplicitCopy
            # element answers yes to. Asking the silent tier here would have
            # refused `[Vector<Int>; 2].copy()` — the one spelling that is
            # unambiguously the author's request for a duplicate.
            #
            # An ABSTRACT element was vetted by the wrapper funnel above
            # (DF-217q), which is bounds-aware where this predicate is not:
            # `type_satisfies_explicit_copy_bound` answers from the tier alone,
            # so `[T; 2]` under a declared `<T: ExplicitCopy>` came back False
            # and the one spelling the bound exists to license was refused.
            if (self.namespace.type_satisfies_explicit_copy_bound(obj_type)
                    or self.namespace.copy_tier(obj_type) == 'abstract'):
                expr.resolved_type = obj_type
                return True, obj_type
            self._error(
                ErrorKind.CANNOT_COPY,
                f"type `{obj_type}` is not Copy; its element type is not copyable",
                expr.line, expr.column,
                hint="use a copyable element type, or `move` to transfer the array"
            )
            return True, None

        # An enum that DECLARED a copying policy (design 139) has a derived
        # payload-deep `copy`, emitted inline by codegen — enums carry no method
        # symbols, so there is nothing for the dispatch above to have found.
        if obj_type.kind == TypeKind.ENUM and obj_type.enum_name:
            if self.namespace.declared_copy_tier(obj_type.enum_name) in ('implicit', 'explicit'):
                expr.resolved_type = obj_type
                return True, obj_type

        # An `Optional<T>` is copyable exactly when its payload is (design 139):
        # the wrapper's tier IS the payload's, so `.copy()` exists precisely
        # where the tier provides one. `None` copies to `None`, `Some` to `Some`
        # of the payload's own copy. This used to be rejected outright, which
        # left `move` as the only way to transfer a `Vector<Int>?` — a wrapper
        # that was somehow less capable than the thing it wrapped.
        if obj_type.kind == TypeKind.OPTIONAL:
            if self.namespace.copy_tier(obj_type) != 'nocopy':
                expr.resolved_type = obj_type
                return True, obj_type
            self._error(
                ErrorKind.CANNOT_COPY,
                f"type `{obj_type}` is not Copy; its payload type is move-only",
                expr.line, expr.column,
                hint="use `move` to transfer the optional, or `.take()` to move "
                     "the payload out in place"
            )
            return True, None

        # A TUPLE is the third wrapper design 139 names, and it gets the rule the
        # other two already had: the tuple carries its strongest element's tier,
        # so `.copy()` exists precisely where that tier provides one. Each element
        # copies at ITS own tier (a `String` retains, a `Vector<Int>` deep-copies),
        # which is what `_emit_tuple_deep_copy` in codegen already does.
        #
        # Without this arm the tuple was the one wrapper the rule named that never
        # got the method, and the two diagnostics contradicted each other: a plain
        # `let u = t` on an ExplicitCopy tuple was refused with "use .copy() for an
        # explicit deep copy", and `t.copy()` was refused with "not Copy" — while
        # `copy_tier` reported that same tuple as 'explicit', exactly the tier the
        # second message said it required. An ExplicitCopy tuple was move-only in
        # practice (DF-151i).
        #
        # Gated the way the optional above is gated rather than on the array's
        # `type_satisfies_copy_bound`: only a move-only element withholds the
        # method, so a tuple mentioning a type PARAMETER stays callable inside a
        # generic body and settles at the instantiation, matching `T?.copy()`.
        if obj_type.kind == TypeKind.TUPLE:
            if self.namespace.copy_tier(obj_type) != 'nocopy':
                expr.resolved_type = obj_type
                return True, obj_type
            offender = next(
                ((i, e) for i, e in enumerate(obj_type.element_types or [])
                 if self.namespace.copy_tier(e) == 'nocopy'),
                None
            )
            where = (f"element {offender[0]} of type `{offender[1]}` is NoCopy"
                     if offender is not None else "an element type is NoCopy")
            self._error(
                ErrorKind.CANNOT_COPY,
                f"type `{obj_type}` is not Copy; {where}",
                expr.line, expr.column,
                hint="use `move` to transfer the tuple, which a destructuring "
                     "`let (a, b) = move t` can then take apart"
            )
            return True, None

        # PROVENANCE SKIP (design 218c §1c, skip 3) — A `.copy()` THE SILENT
        # TIER ANSWERS, ON A SUBSTITUTED CLONE. The chain above asks for a
        # `copy` METHOD or a trivially copyable type, and the refcounted half
        # of the Copy tier (`String`, an escaping closure) is neither: its copy
        # is a retain codegen emits with nothing to look up. In an AUTHORED
        # body the refusal is right. In an instance the spelling is not the
        # author's choice at this type — the template wrote it under an
        # `ExplicitCopy` bound, which every Copy type satisfies and every call
        # site already discharged. `_mono_copy_is_a_retain` is the whole
        # question; its docstring carries the triage.
        if self._mono_copy_is_a_retain(obj_type):
            expr.resolved_type = obj_type
            return True, obj_type

        # Anything else is not Copy.
        self._error(
            ErrorKind.CANNOT_COPY,
            f"type `{obj_type}` is not Copy; `.copy()` requires a trivially-copyable, "
            f"Copy, or ExplicitCopy type",
            expr.line, expr.column
        )
        return True, None

    def _resolve_arc_forward(self, expr: MethodCall, payload_type: Optional[SawType],
                             through: str = "Arc"):
        """Resolve a wrapper payload-method forward (design 21b E2 for Arc,
        design 42 item 1 for Box — `through` names the wrapper for diagnostics).

        Returns `(payload_method_info, payload_type_subst)` if `expr.method_name`
        is an immutable `&self` method on the payload struct `T`; the string
        `"rejected"` if it is a `&var self` method (reported here as an error);
        or `None` if there is no such method (the caller then falls through to
        the ordinary "no method on the wrapper" diagnostic).
        """
        if payload_type is None or payload_type.kind != TypeKind.STRUCT:
            return None
        p_info = self.get_struct_info(payload_type.struct_name, from_type=payload_type)
        if p_info is None:
            return None
        m = self._lookup_method(p_info, expr.method_name, payload_type.type_args)
        if m is None:
            return None
        if getattr(m, "self_mutable", False):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot call `&var self` method `{expr.method_name}` through `{through}` "
                f"— aliased mutation of a shared value is not allowed",
                expr.line, expr.column,
                hint="wrap the payload in a `Mutex` and mutate it inside `lock`"
            )
            return "rejected"
        subst: Dict[str, SawType] = {}
        if p_info.type_params and payload_type.type_args:
            for tp, ta in zip(p_info.type_params, payload_type.type_args):
                subst[tp.name] = ta
        return (m, subst)

    def _check_hash_call(self, expr: MethodCall, obj_type: SawType):
        """Handle a `.hash(&h)` receiver (design 48). Returns (handled, result).

        handled=False means the receiver has a real `hash` method (String, or a
        struct with a synthesized/custom hash) and normal dispatch should
        proceed. handled=True means this call was resolved here: a Hashable
        primitive or auto-conforming (POD struct / payload-free enum) receiver,
        whose `hash` is emitted inline by codegen. A generic type parameter is
        left to the bound-aware resolver.
        """
        type_params = getattr(self, 'current_type_params', {})
        # Opaque generic `T`: leave to the bound-aware resolver (it finds `hash`
        # on a `Hashable` bound).
        if obj_type.kind == TypeKind.STRUCT and obj_type.struct_name in type_params:
            return False, None
        # Concrete type carrying a real `hash` method: normal dispatch.
        if obj_type.kind == TypeKind.STRUCT:
            struct_info = self.get_struct_info(obj_type.struct_name, from_type=obj_type)
            if struct_info and self._lookup_method(struct_info, "hash", obj_type.type_args) is not None:
                return False, None
        elif obj_type.kind == TypeKind.STRING:
            struct_info = self.get_struct_info("String")
            if struct_info and self._lookup_method(struct_info, "hash") is not None:
                return False, None
        # No real method: the receiver must be Hashable (primitive / POD struct /
        # payload-free enum). Otherwise fall through to the normal (error) path.
        if not self._bound_satisfied(obj_type, "Hashable"):
            return False, None
        # Validate the `&var Hasher` argument.
        arg_type = self._check_expression(expr.arguments[0].value)
        ok = (arg_type is not None and arg_type.kind == TypeKind.REFERENCE
              and arg_type.inner_type is not None
              and arg_type.inner_type.kind == TypeKind.STRUCT
              and arg_type.inner_type.struct_name == "Hasher")
        if not ok:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`hash` expects a `&var Hasher` argument, got `{arg_type}`",
                expr.line, expr.column,
                hint="pass a mutable reference to a Hasher: `x.hash(&h)`"
            )
        expr.resolved_type = SawType(TypeKind.VOID)
        return True, SawType(TypeKind.VOID)

    def _check_printable_call(self, expr: MethodCall, obj_type: SawType):
        """Handle `.to_string()` / `.format(into:)` (design 56). Returns
        (handled, result). handled=False means the receiver has a real method
        (a Printable user struct) or is a generic `T` — normal / bound resolution
        proceeds. handled=True means a builtin receiver was resolved inline."""
        mname = expr.method_name
        type_params = getattr(self, 'current_type_params', {})
        # Opaque generic `T`: leave to the bound-aware resolver.
        if obj_type.kind == TypeKind.STRUCT and obj_type.struct_name in type_params:
            return False, None
        # Concrete struct/enum carrying a real method: normal dispatch.
        if obj_type.kind == TypeKind.STRUCT:
            struct_info = self.get_struct_info(obj_type.struct_name, from_type=obj_type)
            if struct_info and self._lookup_method(struct_info, mname, obj_type.type_args) is not None:
                return False, None
        # Builtin (primitive / String) receiver: must be Printable, resolved here.
        if obj_type.kind not in (TypeKind.STRUCT, TypeKind.ENUM, TypeKind.STRING) \
                or (obj_type.kind == TypeKind.STRING):
            pass  # primitives / String handled below
        if not self.namespace.is_printable(obj_type):
            return False, None
        if mname == "to_string":
            if len(expr.arguments) != 0:
                return False, None
            expr.resolved_type = SawType(TypeKind.STRING)
            return True, SawType(TypeKind.STRING)
        # format(into: &var StringBuilder)
        if len(expr.arguments) != 1:
            return False, None
        arg_type = self._check_expression(expr.arguments[0].value)
        ok = (arg_type is not None and arg_type.kind == TypeKind.REFERENCE
              and arg_type.inner_type is not None
              and arg_type.inner_type.kind == TypeKind.STRUCT
              and arg_type.inner_type.struct_name == "StringBuilder")
        if not ok:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`format` expects a `&var StringBuilder` argument, got `{arg_type}`",
                expr.line, expr.column,
                hint="pass a mutable reference to a StringBuilder: `x.format(into: &var b)`"
            )
        expr.resolved_type = SawType(TypeKind.VOID)
        return True, SawType(TypeKind.VOID)

    def _check_type_param_method_call(self, expr: MethodCall, obj_type: SawType,
                                      bounds) -> Optional[SawType]:
        """Resolve `x.method()` where `x` has opaque generic type `T` (design 24
        item 1).

        The method must be provided by one of `T`'s declared trait bounds. Found
        in a bound's trait: check the argument count against that signature,
        check the argument expressions (stamping their annotations), and yield
        the trait method's declared return type — which may be an associated
        type and therefore stays abstract. Provided by no bound: a compile error
        naming the method and the bounds (an unbounded `T` names an empty set).

        Deep argument-type compatibility used to be deferred WHOLESALE: a trait
        method signature MAY mention associated types or the trait's own type
        parameters, and nothing asked whether THIS one does. DF-239b closes
        that: the requirement's signature is resolved at REGISTRATION, in the
        module that declares it, and every parameter whose resolved type names
        nothing abstract — after `Self` is substituted to the receiver's own
        type parameter — takes the ordinary argument check here. What is left
        deferred is what is genuinely undecidable in this body: a parameter
        naming an associated type, a trait type parameter, or the
        requirement's own generic.

        FOUR things are checked. Each of the first three is a SPELLING question
        rather than a typing one — true at every instantiation whatever `T`
        turns out to be. This is the one call form in the language with no
        argument-compatibility loop, so anything it skips reaches codegen, where
        a mismatch is an ICE rather than a diagnostic (DF-239a):

          - argument COUNT (above);
          - ALIASING, through `_check_call_exclusivity` below;
          - REFERENCE-NESS, in `_check_bound_arg_reference_spelling` — a `&Self`
            or `&Item` parameter demands a `&`-spelled argument and a by-value
            one refuses it. `&` is written at the call site in Saw (design 34's
            mirroring rule), so this needs no substitution and no resolution:
            the declared type's own kind answers it.
          - the argument's TYPE, for every DECIDABLE parameter
            (`_bound_call_expected_type`) — DF-239b. It runs where the ordinary
            method path's does, over the same `_arg_type_ok` predicate and with
            the same literal-adoption stamp ahead of it, so `a.concrete("hi")`
            against `func concrete(&self, n: Int)` is a diagnostic at the call
            rather than `Type of #2 arg mismatch: i64 != i8*` at codegen.

        WHY RESOLUTION HAD TO MOVE (the reason this was its own finding rather
        than DF-239a's last cell): the declared types are raw spellings, and
        resolving one HERE runs design 194's prelude gate against the caller's
        module. A trait declared in a module that imports `std.data` and takes a
        `data.Data` would then be uncallable from a module that does not — the
        error naming a type the caller never wrote. Declaration-time resolution
        is what makes the check safe across modules; see
        `TraitMethodSymbol.resolved_param_types`.

        A trait method has no analyzable body, so it contributes no suspend edge
        — a conservative non-suspending leaf, matching how opaque/imported
        callees are treated (design 22 §5).
        """
        tp_name = obj_type.struct_name
        for bound in bounds:
            trait = self.get_trait_info(bound)
            if trait is None:
                # A `Copy`-family / `Send` / `Sync` marker bound with no user
                # methods; it grants no callable method here (`.copy()` under a
                # Copy bound is handled earlier, in `_check_copy_call`).
                continue
            method_sym = trait.methods.get(expr.method_name)
            if method_sym is None:
                continue
            # `param_names` excludes the `self` receiver (which `param_types`
            # carries as a placeholder at index 0), so it is the arity to match.
            expected = len(method_sym.param_names)
            arity_ok = len(expr.arguments) == expected
            if not arity_ok:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{expr.method_name}` takes {expected} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            # DF-239b: the expected type per argument, where the requirement's
            # resolved signature makes one decidable. `None` everywhere is the
            # pre-DF-239b behaviour and is what an unresolved symbol, an
            # unmappable label list or a genuinely abstract parameter gets.
            slots = (self._bound_call_param_slots(expr, method_sym)
                     if arity_ok else None)
            off, mapping = slots if slots is not None else (0, [])
            for i, arg in enumerate(expr.arguments):
                param = mapping[i] if i < len(mapping) else None
                expected = (None if param is None else
                            self._bound_call_expected_type(
                                method_sym, param + off, obj_type))
                if isinstance(arg.value, ClosureExpr):
                    self._check_closure(arg.value, expected,
                                        as_call_argument=True)
                    continue
                if expected is not None:
                    # Design 87/205's literal adoption, ahead of the check, on
                    # the same terms as the ordinary method path: a bare `1` at
                    # a `UInt8` parameter is that parameter's literal, not a
                    # platform `Int` being narrowed.
                    self._apply_literal_expected_type(arg.value, expected)
                arg_type = self._check_expression(arg.value)
                if expected is None or arg_type is None:
                    continue
                if self._try_existential_arg_coercion(arg, arg_type, expected):
                    continue
                if ((expected.kind == TypeKind.REFERENCE)
                        != isinstance(arg.value, ReferenceExpr)):
                    # A missing or surplus `&` is `_check_bound_arg_reference_
                    # spelling`'s to report, and its message carries the fixit.
                    # One mistake, one diagnostic: the type mismatch this also
                    # produces is the same fact said worse.
                    continue
                if not self._arg_type_ok(arg.value, arg_type, expected):
                    name = (method_sym.param_names[param]
                            if param < len(method_sym.param_names)
                            else str(i + 1))
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"argument `{name}` expects `{expected}` but got "
                        f"`{arg_type}`",
                        arg.value.line, arg.value.column,
                        hint=self._int_conversion_hint(arg_type, expected))
            if arity_ok:
                self._check_bound_arg_reference_spelling(
                    expr, obj_type, method_sym)
            # design 239: an `equals`/`compare` reached through an
            # Equatable/Comparable bound is the comparison the OPERATOR is, so
            # codegen lowers it with the operator's own emitter rather than by
            # mangling a per-type symbol. Most conforming types have no such
            # symbol — `Int` never had one and `String`'s `equals` is its own
            # by-value API, not the requirement's body — so the mangled path
            # ICEd at exactly the instantiations a generic bound exists to
            # serve.
            if (bound in ("Equatable", "Comparable")
                    and expr.method_name in ("equals", "compare")
                    and len(expr.arguments) == 1):
                expr.comparison_dispatch = bound
            # The Law of Exclusivity, through the same funnel every other call
            # form uses (design 193 unit 4). Deep argument TYPING is deferred
            # here — a trait signature may mention associated types — but
            # aliasing is not a typing question: `s.pair(&var p, &var p)` is the
            # same violation at every instantiation, and refusing it in the
            # generic body is what keeps it out of post-monomorphization errors.
            # `param_types[0]` is the `self` placeholder.
            self._check_call_exclusivity(
                [a.value for a in expr.arguments],
                list(method_sym.param_types or [])[1:],
                receiver=expr.object,
                receiver_mutable=bool(getattr(method_sym, 'self_mutable', False)),
                param_names=list(method_sym.param_names or []))
            # design 70 (A5): a method call on a type-PARAMETER receiver makes the
            # enclosing body effect-polymorphic — its suspendability depends on the
            # concrete `T`. A trait method contributes no edge here (abstract body),
            # so instead we flag the body; a call to it with concrete type args then
            # re-infers effects on the instantiation.
            self._effect_mark_poly()
            if method_sym.return_type is None:
                return SawType(TypeKind.VOID)
            return self._resolve_type(method_sym.return_type)
        # Not provided by any of `T`'s bounds (or `T` is unbounded).
        bound_list = ", ".join(bounds) if bounds else ""
        if bounds:
            hint = (f"none of `{tp_name}`'s bounds ({bound_list}) declare a "
                    f"method `{expr.method_name}`")
        else:
            hint = (f"`{tp_name}` is unbounded; add a trait bound whose trait "
                    f"declares `{expr.method_name}` (e.g. `<{tp_name}: SomeTrait>`)")
        self._error(
            ErrorKind.UNDEFINED_FUNCTION,
            f"type parameter `{tp_name}` has no method `{expr.method_name}`; "
            f"its bounds are [{bound_list}]",
            expr.line, expr.column,
            hint=hint
        )
        return None

    def _bound_call_param_slots(self, expr: MethodCall, method_sym):
        """Which DECLARED parameter each argument fills, or None.

        THE ONE argument -> parameter mapping on the generic-bound call path
        (obligation 1). ENTRY POINTS: `_check_type_param_method_call`'s deep
        type check (DF-239b) and `_check_bound_arg_reference_spelling`'s
        reference-spelling check (DF-239a). Both judge a per-parameter property
        of an argument, and two copies of "which parameter is this" would drift
        the moment labels grew a rule.

        Returns `(off, mapping)`: `off` is the `self` placeholder's width in
        `param_types` (1 for a receiver requirement, 0 for a `static` one), and
        `mapping[i]` indexes `param_names` for argument `i`. `None` means the
        mapping cannot be established — an unrecognized label is somebody else's
        diagnostic, and judging the call at guessed positions would pile a wrong
        error on top of a right one.
        """
        param_types = list(method_sym.param_types or [])
        param_names = list(method_sym.param_names or [])
        off = len(param_types) - len(param_names)
        if off < 0:
            return None
        # Labels map by name (design 66).
        if self._call_has_labels(expr):
            mapping = []
            for arg in expr.arguments:
                label = getattr(arg, 'name', None)
                if label is None or label not in param_names:
                    return None
                mapping.append(param_names.index(label))
            return off, mapping
        return off, list(range(len(expr.arguments)))

    def _bound_call_expected_type(self, method_sym, slot: int,
                                  obj_type: SawType):
        """The parameter type at `slot` if it is DECIDABLE in this body, else
        None (DF-239b).

        TWO steps, and the order matters:

          1. take the DECLARATION-TIME resolution (`resolved_param_types`),
             never the raw spelling — the raw one means whatever the DECLARING
             module's imports say, and re-resolving it here would ask the
             caller's namespace a question about someone else's module;
          2. substitute `Self` to the receiver's own type parameter, then refuse
             the parameter if what is left names anything abstract — an
             associated type, a trait type parameter, the requirement's own
             generic (`abstract_type_names` carries all three, collected where
             they are known).

        After step 2 a surviving type is one that means the same thing at every
        instantiation: `Int` is `Int`, and `&Self` has become `&T`, which the
        body can compare against because `T` is its own parameter. `T` itself is
        NOT abstract for this purpose — it is the very type the receiver has.

        A symbol with no declaration-time resolution (the shallow
        `register_module_from_ast` path builds those) answers None for every
        slot, which is exactly the deferral this call form had before.
        """
        resolved = method_sym.resolved_param_types
        if not resolved or slot < 0 or slot >= len(resolved):
            return None
        declared = resolved[slot]
        if declared is None:
            return None
        substituted = self._substitute_self_type(declared, obj_type) or declared
        if self._type_names_any(substituted, method_sym.abstract_type_names):
            return None
        return substituted

    def _type_names_any(self, t, names, depth: int = 0) -> bool:
        """Whether `t` mentions any name in `names`, at any depth.

        The abstractness test behind `_bound_call_expected_type`. Every slot a
        name can sit in is walked, because `Vector<Item>` and `(Int, Item)` are
        as abstract as a bare `Item` and neither is visible at the root.
        """
        if t is None or not names or depth > 16:
            return False
        for slot in ('struct_name', 'enum_name', 'type_param_name',
                     'existential_trait'):
            value = getattr(t, slot, None)
            if value and value.split('.')[-1] in names:
                return True
        for child in (t.inner_type, t.array_element_type, t.func_return_type):
            if self._type_names_any(child, names, depth + 1):
                return True
        for group in (t.type_args, t.element_types, t.param_types):
            for child in (group or []):
                if self._type_names_any(child, names, depth + 1):
                    return True
        return False

    # design 218 unit 3, the MINIMAL SLICE pulled forward into unit 1.5 (user
    # ruling, Sep 1) — the requirement name to the trait that declares it.
    # `hash` is deliberately absent: see `_builtin_requirement_call`.
    _BUILTIN_REQUIREMENT_TRAITS = {"equals": "Equatable",
                                   "compare": "Comparable"}

    def _builtin_requirement_call(self, expr: MethodCall, obj_type, method_info):
        """`a.compare(&b)` / `a.equals(&b)` where the CONFORMANCE BODY IS IN
        CODEGEN.

        THE GAP THIS CLOSES (DF-284c). Some conformances have no method
        anywhere the checker can see, because their body is synthesized during
        lowering instead: a primitive conforms to Equatable/Comparable BUILTIN
        (`is_equatable` / `is_comparable` answer structurally off the KIND) and
        `_emit_equals` / `_emit_compare` are the bodies. So the requirement
        resolves through a BOUND — design 239 routes it there to the operator's
        own emitter, stamping `comparison_dispatch` — and resolves NOWHERE once
        the receiver is concrete: `let a: Int = 3; a.compare(&b)` was `type
        `Int` has no method `compare``, hinting `abs, clamp, is_even, …`.

        Invisible until design 218 unit 1.5 stage 2 made a monomorphized
        instance's diagnostics real. A clone has no type parameters and
        therefore no bounds, so `rank<T: Comparable>`'s `a.compare(&b)` at
        `T = UInt8` reached exactly this concrete path and was refused — in a
        program that compiles and runs correctly, because codegen supplies the
        body the checker cannot see.

        THE ANSWER IS THE ONE DESIGN 239 ALREADY BUILT, which is what makes
        behavioural identity a property of the code rather than a claim: stamp
        `comparison_dispatch` and codegen lowers with `_emit_equals` /
        `_emit_compare` — the SAME emitters `==` and `<` use, so design 252's
        unsigned ordering, Float's IEEE ordering, String's content order and
        an enum's payload-deep order are all reached through the one path that
        decides them. No symbol is minted and no body moves.

        THE SET, and it is a PREDICATE rather than a list — "the conformance
        has no callable method here". Probed cell by cell rather than assumed,
        because the first spelling of this fence said `primitives only` and two
        of the four blocked corpus tests walked straight past it:
          * PRIMITIVES (`Int`, the fixed widths, `Float`, `Bool`) and any
            distinct ALIAS over one — `type_satisfies_bound` resolves aliases,
            which is the design-252 lesson restated;
          * `@synthesize`d ENUM conformances, whose derived body is
            `_emit_enum_compare` and which therefore have no method either. A
            `@synthesize`d STRUCT is NOT in the set — it gets a real method, so
            it never reaches here and keeps its own body;
          * `String`, the one member that DOES have a same-named method:
            `String.equals`/`compare` take `other` BY VALUE (design 239 records
            that asymmetry deliberately), which is a different function from
            the requirement, whose `other` is lent. Hence `method_info` is not
            consulted for STRING and is required to be None for everything
            else.

        WHAT CANNOT BE INTERCEPTED, by construction: a type with a real
        `equals`/`compare` — hand-written or struct-`@synthesize`d — keeps it,
        because this is asked only where lookup found nothing (or found
        String's by-value API). And `s.equals(t)`, the by-value spelling,
        never enters: the `&` is required, so String's own API is untouched at
        every spelling that works today.

        `hash` is NOT here. It has the same shape, but it is not part of the
        blocker: `k.hash(&var h)` through a `T: Hashable` bound compiles AND
        lowers at a primitive today (probed), so nothing regressed and nothing
        is owed. It stays with the rest of unit 3.

        A missing `&` falls through to the ordinary refusal rather than
        inventing a second diagnostic for a spelling that path already teaches.
        """
        if obj_type is None:
            return None
        is_string = obj_type.kind == TypeKind.STRING
        if method_info is not None and not is_string:
            return None
        bound = self._BUILTIN_REQUIREMENT_TRAITS.get(expr.method_name)
        if bound is None or len(expr.arguments) != 1:
            return None
        if not self.namespace.type_satisfies_bound(obj_type, bound):
            return None
        arg = expr.arguments[0].value
        if not isinstance(arg, ReferenceExpr):
            return None
        expected = SawType(TypeKind.REFERENCE, inner_type=obj_type)
        arg_type = self._check_expression(arg)
        if arg_type is None or not self._arg_type_ok(arg, arg_type, expected):
            return None
        trait = self.namespace.lookup_trait(bound)
        method_sym = trait.methods.get(expr.method_name) if trait else None
        if method_sym is None or method_sym.return_type is None:
            return None
        expr.comparison_dispatch = bound
        return method_sym.return_type

    def _check_bound_arg_reference_spelling(self, expr: MethodCall,
                                            obj_type: SawType,
                                            method_sym) -> None:
        """The reference-spelling half of argument compatibility, for a call on a
        trait-bounded type parameter (DF-239a).

        `_check_type_param_method_call` defers deep argument typing because a
        trait signature may name associated types. Reference-NESS is not part of
        what it defers: Saw writes the borrow at the call site (design 34), so a
        parameter declared `&X` demands a `&`-spelled argument and a by-value one
        refuses it, at every instantiation, whatever `X` denotes. The DECLARED
        type answers the question on its own — no `Self` substitution, no
        resolution, no prelude gate — which is what makes it safe to ask here.

        Skipping it is not a lenience but an ICE: a generic body calling
        `a.merge(b)` against `func merge(&self, other: &Self)` type-checked, then
        monomorphized into `Type of #2 arg mismatch: %"Bag"* != %"Bag"`. The two
        directions are one rule and both were unchecked:

        | argument | parameter | before | after |
        |---|---|---|---|
        | value      | `&X` / `&var X` | ICE at codegen | error, fixit `&b`   |
        | `&`/`&var` | by-value `X`    | ICE at codegen | error, drop the `&` |
        | `&x`       | `&var X`        | error          | error (unchanged)   |
        | `&var x`   | `&X`            | error          | error (unchanged)   |

        The last two rows are `_check_reference_sigils`, reached through
        `_check_call_exclusivity`; it deliberately declines the first two,
        deferring them to "the caller's compatibility check" — the one this call
        form does not have.

        `Self` is substituted for the RENDERING only, so the diagnostic says
        `&T` (the reader's own type parameter) rather than `&Self`.
        """
        param_types = list(method_sym.param_types or [])
        param_names = list(method_sym.param_names or [])
        slots = self._bound_call_param_slots(expr, method_sym)
        if slots is None:
            return
        off, mapping = slots
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] + off
            if p >= len(param_types):
                continue
            declared = param_types[p]
            if declared is None:
                continue
            wants_ref = declared.kind == TypeKind.REFERENCE
            gave_ref = isinstance(arg.value, ReferenceExpr)
            if wants_ref == gave_ref:
                continue
            name = param_names[mapping[i]]
            rendered = self._substitute_self_type(declared, obj_type) or declared
            if wants_ref:
                sigil = "&var " if declared.reference_mutable else "&"
                target = self._render_lvalue_path(arg.value)
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{name}` expects `{rendered}`, but the borrow is "
                    f"not written",
                    arg.value.line, arg.value.column,
                    hint=f"call sites mirror the parameter's reference spelling "
                         f"— write `{sigil}{target}`"
                )
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{name}` expects `{rendered}` by value, but a "
                    f"reference is written",
                    arg.value.line, arg.value.column,
                    hint="drop the `&` — the parameter takes ownership of its "
                         "argument"
                )

    def _check_field_call(self, expr: MethodCall, func_type: SawType) -> Optional[SawType]:
        """Check a call through a function-typed struct field: `obj.field(args)`
        (design 24 item 3).

        This is an indirect call. Suspendability follows the field's type: a
        non-`sync` function-typed field conservatively marks the caller
        suspending (`_effect_indirect_call`), exactly like a call through a
        function-typed local or parameter. The node is flagged for codegen so it
        lowers to a field load + closure invocation rather than method dispatch.
        """
        # design 22/24: indirect call — non-`sync` field type => caller suspends.
        self._effect_indirect_call(func_type, expr.line)
        expr.is_field_call = True  # consumed by codegen
        param_types = func_type.param_types or []
        return_type = func_type.func_return_type or SawType(TypeKind.VOID)
        # Design 66: a function-typed field is a STRUCTURAL closure type — no
        # parameter names to label against.
        if self._call_has_labels(expr):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"labeled arguments are not allowed when calling through the "
                f"function-typed field `{expr.method_name}` (closure types are "
                f"structural)", expr.line, expr.column)
            return return_type
        if len(expr.arguments) != len(param_types):
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"field `{expr.method_name}` is a function taking {len(param_types)} "
                f"argument(s), but {len(expr.arguments)} were given",
                expr.line, expr.column
            )
            return return_type
        for i, (arg, expected_type) in enumerate(zip(expr.arguments, param_types)):
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type, as_call_argument=True)
            else:
                arg_type = self._check_expression(arg.value)
            if arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument {i + 1} expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column,
                    hint=self._int_conversion_hint(arg_type, expected_type)
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        self._check_call_exclusivity([a.value for a in expr.arguments], param_types)
        return return_type

    # ---- design 51: `any Trait` existential dispatch, construction, coercion ----

    def _existential_receiver_trait(self, obj_type):
        """If `obj_type` names an erased receiver, return its trait name, else
        None. Accepts `any T`, `&any T`, and `Box<any T, A>`."""
        if obj_type is None:
            return None
        if obj_type.kind == TypeKind.EXISTENTIAL:
            return obj_type.existential_trait
        if (obj_type.kind == TypeKind.REFERENCE and obj_type.inner_type is not None
                and obj_type.inner_type.kind == TypeKind.EXISTENTIAL):
            return obj_type.inner_type.existential_trait
        if (obj_type.kind == TypeKind.STRUCT and obj_type.struct_name == "Box"
                and obj_type.type_args
                and obj_type.type_args[0].kind == TypeKind.EXISTENTIAL):
            return obj_type.type_args[0].existential_trait
        return None

    def _check_existential_method_call(self, expr, obj_type, trait_name):
        """Type-check dynamic dispatch through an erased receiver: resolve the
        method against the trait signature, check arguments, and propagate the
        trait method's declared effect (a non-`sync` method suspends, like an
        indirect call; a `sync` method stays sync-callable through `any`)."""
        # Erased-box downcasting (design 72): `b.is<T>()` / `b.take<T>()` on an
        # owned `Box<any Trait>`, disambiguated by the explicit type argument.
        if (expr.method_name in ("is", "take")
                and getattr(expr, 'type_args', None)
                and obj_type.kind == TypeKind.STRUCT
                and obj_type.struct_name == "Box"):
            return self._check_erased_downcast(expr, obj_type, trait_name)

        trait = self.get_trait_info(trait_name)
        if trait is None:
            self._error(ErrorKind.UNKNOWN_TYPE,
                        f"unknown trait `{trait_name}`", expr.line, expr.column,
                        hint=self._retired_trait_hint(trait_name))
            return None
        tmethod = trait.methods.get(expr.method_name)
        if tmethod is None:
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"trait `{trait_name}` has no method `{expr.method_name}` to "
                f"dispatch through `any {trait_name}`",
                expr.line, expr.column)
            return None
        # Arg count (param_types[0] is the VOID self placeholder).
        expected = (tmethod.param_types or [])[1:]
        if len(expr.arguments) != len(expected):
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{trait_name}.{expr.method_name}` takes {len(expected)} "
                f"argument(s), but {len(expr.arguments)} were given",
                expr.line, expr.column)
            return tmethod.return_type
        for i, arg in enumerate(expr.arguments):
            arg_type = self._check_expression(arg.value)
            if (arg_type is not None and expected[i] is not None
                    and not self._types_compatible(arg_type, expected[i])):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument {i + 1} expects `{expected[i]}` but got `{arg_type}`",
                    arg.value.line, arg.value.column,
                    hint=self._int_conversion_hint(arg_type, expected[i]))
            self._check_value_transfer(arg.value, expected[i], "call argument",
                                       arg.value.line, arg.value.column)
        # The Law of Exclusivity, through the same funnel every other call form
        # uses (design 193 unit 4). Erasing a receiver erases nothing about
        # ALIASING: `s.pair(&var p, &var p)` is the same violation whether `s`
        # is a `Counter` or an `&any Pairer`, and this call form simply never
        # joined an access set. The trait SIGNATURE supplies the parameter types
        # (dispatch is by that signature), so the reference sigils are checked
        # against it too.
        self._check_call_exclusivity(
            [a.value for a in expr.arguments], list(expected),
            receiver=expr.object,
            receiver_mutable=bool(getattr(tmethod, 'self_mutable', False)),
            param_names=list(getattr(tmethod, 'param_names', None) or []))
        # Effect propagation: the call carries the TRAIT signature's effect.
        if not getattr(tmethod, 'is_sync', False):
            self._effect_direct_source(
                f"a call through `any {trait_name}` dispatch", expr.line)
            # design 223 unit 3 (DF-223b): …and that source is CONSERVATIVE, so
            # it never makes a frame. Record the site; `finalize_effects` refuses
            # it if some conformance's body really suspends, once the fixpoint
            # can say so.
            self._existential_dispatch_sites.append(
                (trait_name, expr.method_name, expr.line, expr.column,
                 self._get_current_source_file()))
        expr.existential_dispatch = trait_name
        return tmethod.return_type

    def _check_erased_downcast(self, expr, box_type, trait_name):
        """Type-check erased-box downcasting (design 72 v1).

        `b.is<T>()` -> `Bool` (a borrow: the box stays live). `b.take<T>()` -> `T?`
        and CONSUMES the box (the receiver binding is marked moved; on a runtime
        id miss the box drops and the result is `None`; `is<T>()` first lets a
        caller branch without consuming). `T` is given explicitly (no inference)
        and must be a concrete type conforming to the erased trait. Catch-side
        match-on-concrete sugar is out of scope (future)."""
        op = expr.method_name
        result_ty = (SawType(TypeKind.BOOL) if op == "is" else None)
        type_args = expr.type_args or []
        if len(type_args) != 1:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{op}<T>()` requires exactly one explicit type argument",
                expr.line, expr.column)
            return result_ty
        if len(expr.arguments) != 0:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{op}<T>()` takes no value arguments",
                expr.line, expr.column)
        target = self._resolve_type(type_args[0])
        conc_name = None
        if target.kind == TypeKind.STRUCT:
            conc_name = target.struct_name
        elif target.kind == TypeKind.STRING:
            conc_name = "String"
        if conc_name is None or not self.namespace.type_conforms_to(conc_name, trait_name):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{target}` is not a concrete type conforming to `{trait_name}`, "
                f"so it cannot be a downcast target for `{op}<T>()`",
                expr.line, expr.column,
                hint="the type argument must be a concrete conforming type")
            return SawType(TypeKind.OPTIONAL, inner_type=target) if op == "take" else result_ty
        expr.erased_downcast = {
            'op': op,
            'target': target,
            'box_type': box_type,
            'trait': trait_name,
        }
        if op == "is":
            return SawType(TypeKind.BOOL)
        # `take` consumes the box — mark the receiver binding moved (like a move),
        # so a later use is a use-after-move error and scope teardown skips it.
        if isinstance(expr.object, Identifier):
            var_info = self.current_scope.lookup(expr.object.name)
            if var_info is not None:
                if self._binding_move_info(var_info) is not None:
                    _, move_line, _ = self._binding_move_info(var_info)
                    self._error(
                        ErrorKind.USE_AFTER_MOVE,
                        f"use of moved variable `{expr.object.name}`",
                        expr.line, expr.column,
                        hint=f"value was already moved at line {move_line}")
                else:
                    self._mark_binding_moved(var_info, expr.object.name,
                                             expr.line, expr.column)
        return SawType(TypeKind.OPTIONAL, inner_type=target)

    def _check_erased_box_make(self, expr, existential_type):
        """`Box<any Trait>.make(v)` built erased-directly (design 51): the concrete
        `v` must conform to the trait; the result is `Box<any Trait, A>`."""
        trait_name = existential_type.existential_trait
        # Object safety of the erased trait (this construction site is not a
        # declared signature, so it was not covered by the signature-level pass).
        self._check_object_safety(trait_name, expr.line, expr.column)

        if expr.method_name == "try_make":
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`Box<any Trait>.try_make(...)` is not yet supported — use "
                "`Box<any Trait>.make(...)` (the fallible erased factory is deferred)",
                expr.line, expr.column)
            return None

        # Allocator: the second type arg, or Global by default.
        type_args = [self._resolve_type(t) for t in (expr.object.type_args or [])]
        type_args = self._append_default_type_args("Box", type_args)
        allocator = type_args[1] if len(type_args) > 1 else SawType(
            TypeKind.STRUCT, struct_name="GlobalAllocator")

        if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                "`Box<any Trait>.make(...)` takes exactly one positional value",
                expr.line, expr.column)
            return None

        concrete = self._check_expression(expr.arguments[0].value)
        box_result = SawType(TypeKind.STRUCT, struct_name="Box",
                             type_args=[existential_type, allocator])
        if concrete is None:
            return box_result
        if self._reject_primitive_erasure(
                concrete, trait_name,
                expr.arguments[0].value.line, expr.arguments[0].value.column):
            return box_result
        conc_name = None
        if concrete.kind == TypeKind.STRUCT:
            conc_name = concrete.struct_name
        elif concrete.kind == TypeKind.STRING:
            conc_name = "String"
        if conc_name is None or not self.namespace.type_conforms_to(conc_name, trait_name):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{concrete}` does not conform to `{trait_name}`, so it cannot be "
                f"erased into `Box<any {trait_name}>`",
                expr.arguments[0].value.line, expr.arguments[0].value.column)
            return box_result
        # The value is MOVED into the box (consumed).
        self._check_value_transfer(expr.arguments[0].value, concrete,
                                   "call argument",
                                   expr.arguments[0].value.line,
                                   expr.arguments[0].value.column)
        expr.erased_box_make = {
            'trait': trait_name,
            'concrete': concrete,
            'allocator': allocator,
            'try_make': False,
        }
        return box_result

    def _check_spawned_call_argument(self, expr, form: str, example: str):
        """THE COOPERATIVE SPAWN FUNNEL (design 242 unit 3, obligation 1).

        Both cooperative spawn forms hand the engine a DIRECT CALL to a free
        function, and everything between "one positional argument" and "the
        root is registered" is the same question asked twice. It is asked here.

        ENTRY POINTS, both of them:
          * `_check_taskgroup_spawn` — `group.spawn(f(args))` (design 52b).
          * `_check_task_spawn` — `Task.spawn(f(args))` (design 242 ruling 10:
            the CALL form is the Task engine's primitive, because a brace body
            cannot suspend and a suspending body is the engine's whole point).

        `form` is the spelling the diagnostics print and `example` a call in
        that spelling. Returns `(spawn_name, result_type, inner)` — the
        MONOMORPHIZED root symbol, the body's return type and the (possibly
        reinterpreted) inner call node — or None after a diagnostic.
        """
        if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{form}(...)` takes exactly one positional argument: a call "
                f"to the function to run as a task, e.g. `{example}`",
                expr.line, expr.column)
            return None
        inner = expr.arguments[0].value
        if isinstance(inner, StructInit) and self.get_struct_info(inner.struct_name) is None:
            as_call = self._reinterpret_struct_init_as_call(inner)
            if as_call is not None:
                inner.as_function_call = as_call
                expr.arguments[0].value = as_call
                inner = as_call
        if not isinstance(inner, FunctionCall):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{form}(...)` expects a direct call to a free function, "
                f"e.g. `{example}`",
                expr.line, expr.column)
            return None
        self._restore_authored_call(inner)
        sentinel = self._effect_absorb_scope()
        inner_type = self._check_expression(inner)
        self._effect_unabsorb(sentinel)
        result_type = inner_type if inner_type is not None else SawType(TypeKind.VOID)
        if self._reject_never_task_body(
                f"`{inner.name}`",
                "the task never completes and `join` on its handle could never "
                "return", result_type, expr.line, expr.column):
            return None
        spawn_name = getattr(inner, 'resolved_symbol', None) or inner.name
        if getattr(inner, 'type_args', None):
            resolved_args = [self._resolve_type(a) for a in inner.type_args]
            if not all(self._is_concrete_type(a) for a in resolved_args):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{form}(...)` of a generic function requires concrete "
                    f"type arguments", expr.line, expr.column)
                return None
            spawn_name = self._effect_queue_fn_mono(spawn_name, resolved_args)
            inner.name = spawn_name
            inner.type_args = None
        return (spawn_name, result_type, inner)

    def _task_handle_type(self, result_type):
        """The cooperative handle for a body of this result type (design 102
        item 1): a `Void` body carries no result slot, so it yields the distinct
        `VoidTask` rather than a `Task<Void>` nothing could write down."""
        if result_type.kind == TypeKind.VOID:
            return SawType(TypeKind.STRUCT, struct_name="VoidTask")
        return SawType(TypeKind.STRUCT, struct_name="Task", type_args=[result_type])

    def _check_task_spawn(self, expr: FunctionCall) -> Optional[SawType]:
        """`Task.spawn(work(3))` — the background-singleton spawn form (design
        242 ruling 3, spelled by ruling 10).

        The task rides the ambient cooperative scheduler in a group the program
        never declares: lazily built on first use, cancelled-then-joined at
        `main`'s return. Three things distinguish it from `group.spawn`:

          * BORROWS ARE BANNED AT THE FORM (ruling 7). A detachable task has no
            join to release a borrow, and enforcing it HERE rather than at
            `detach()` means the checker never has to trace a handle's
            provenance through the program.
          * THE HANDLE IS MUST-CONSUME (ruling 5), minted through the same
            funnel `Thread.spawn` uses.
          * IT NEEDS A HOSTED ENTRY. The background group is closed from the
            synthesized `main`, and a freestanding image has neither.
        """
        resolved = self._check_spawned_call_argument(
            expr, "Task.spawn", "Task.spawn(worker(n))")
        if resolved is None:
            return None
        spawn_name, result_type, inner = resolved
        handle_type = self._task_handle_type(result_type)
        if self.freestanding:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "freestanding profile: `Task.spawn` needs the process-wide "
                "background task group, which is closed at `main`'s return — "
                "a freestanding image has no such entry point",
                expr.line, expr.column,
                hint="declare a `TaskGroup` and spawn into it with "
                     "`group.spawn(work(...))`: the group is the scope that "
                     "says where the tasks end")
            return handle_type
        # ruling 7: no borrow reaches a background task. `_spawn_borrow_sources`
        # is the funnel that knows every position one can be written in — a
        # capture list inside the spawned call, and a `&`/`&var` argument of it
        # — so the ban is stated once, over that list, rather than re-derived.
        for source in self._spawn_borrow_sources(expr, inner):
            sigil = "&var" if source.mutable else "&"
            where = ("a capture" if source.kind == 'capture'
                     else "an argument")
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`Task.spawn` accepts no borrows: `{sigil} {source.name}` is "
                f"{where} of the spawned call",
                source.line, source.column,
                hint="a background task outlives the statement that spawned it "
                     "and may be detached, so there is no join to end the "
                     "borrow at. Spawn into a `TaskGroup` — a group's scope IS "
                     "the borrow's extent (design 189) — or hand the task an "
                     "owned value, an `Arc` or a `Channel`")
            # Hand the handle type back rather than None: the binding stays
            # typed, so a refused spawn reports the borrow and not a cascade of
            # `undefined variable` at every later use. Nothing is recorded and
            # no obligation is minted — the compile has already failed, so the
            # transform never runs.
            return handle_type
        self._effect_record_spawn(spawn_name, result_type)
        self._effect_record_background_spawn(spawn_name)
        expr.spawn_root = spawn_name
        expr.resolved_type = handle_type
        # ruling 5: the obligation is minted AT THE FORM, which is what keeps
        # `group.spawn`'s handles out of it (ruling 6). See the funnel in
        # `types.py`.
        self._mint_spawn_obligation(
            expr,
            "VoidTask" if result_type.kind == TypeKind.VOID
            else f"Task<{result_type}>",
            "Task.spawn")
        return handle_type

    def _check_taskgroup_spawn(self, expr, group_type):
        """`group.spawn(f(args))` (design 52b item 2). Validate the argument is a
        direct call to a free function, record `f` a spawn root (so the coro
        transform builds its frame + `Resumable` conformance + a `__spawn_<f>`
        helper), and yield `Task<T>` with `T` = f's return type. Absorbs the
        callee's suspension — spawning enqueues; it does not itself suspend — so
        the enclosing function does not become suspending merely by spawning.

        The argument's own validation — the arity, design 66's fully-labeled
        `StructInit` reinterpretation, the direct-call requirement, the
        absorbed effect check, the `Never` refusal and design 70's
        monomorphization — is `_check_spawned_call_argument`, which
        `Task.spawn` asks the same way."""
        resolved = self._check_spawned_call_argument(
            expr, "group.spawn", "group.spawn(worker(n))")
        if resolved is None:
            return None
        spawn_name, result_type, inner = resolved
        sources = self._spawn_borrow_sources(expr, inner)
        refused = self._check_spawn_borrow_order(expr, sources)
        self._register_task_capture_borrows(expr, sources, refused)
        self._effect_record_spawn(spawn_name, result_type)
        # design 75 (A2): if the receiver group was built multi-threaded
        # (`TaskGroup(threads: N)`), record this spawn root so the coroutine
        # transform gates its frame on `Send` (it may cross to a worker thread).
        if isinstance(expr.object, Identifier):
            recv_info = self.current_scope.lookup(expr.object.name)
            if recv_info is not None and getattr(recv_info, 'is_mt_group', False):
                self._mt_spawn_roots.add(spawn_name)
        expr.spawn_root = spawn_name
        handle_type = self._task_handle_type(result_type)
        # Stamp the handle type so the transform's `__spawn_<f>` rewrite can carry
        # it onto the replacement call (needed when a suspending spawner makes the
        # `let h = group.spawn(...)` binding frame-resident and must type it).
        expr.resolved_type = handle_type
        return handle_type

    def _spawn_borrow_sources(self, spawn_expr, inner):
        """Every root a `group.spawn(...)` borrows for its task's life.

        THE FUNNEL (obligation 1). The rule this feeds quantifies over "every
        position where a spawned task takes a reference to its spawner", and
        there are exactly TWO. Both entry points are here, and both consumers —
        `_check_spawn_borrow_order` (design 188's LIFO rule) and
        `_register_task_capture_borrows` (design 189's extent) — read this list
        rather than walking the call themselves:

          * a borrow CAPTURE in a closure the spawned call carries — `[&x]` /
            `[&var x]` (design 189). Found through `_closures_in`, so a closure
            anywhere inside the spawned call counts.
          * a `&` / `&var` ARGUMENT of the spawned call itself (design 201). The
            coroutine transform lowers it to a frame-resident pointer into the
            spawner's storage, which is the SAME extent the capture has, spelled
            at the call instead of in a capture list.

        Deliberately NOT a source: a reference created by a NESTED call inside
        the spawned call's arguments (`group.spawn(f(g(&var n)))`). `g` runs
        synchronously at the spawn site and its borrow dies with the statement,
        so nothing outlives it. The Law still sees it — it is an ordinary
        design-199 access-set entry of the spawning call.

        Order is captures then arguments; each source's ROOT is what gets
        borrowed, so `f(&var p.x)` charges `p` exactly as a place borrow does.
        """
        out = []
        for closure in self._closures_in(inner):
            for spec in (getattr(closure, 'capture_specs', None) or []):
                if spec.mode not in ('ref', 'ref_var'):
                    continue
                out.append(_SpawnBorrow(
                    key=id(spec), kind='capture', name=spec.name,
                    mutable=(spec.mode == 'ref_var'),
                    line=spec.line or spawn_expr.line,
                    column=spec.column or spawn_expr.column))
        for arg in (getattr(inner, 'arguments', None) or []):
            value = arg.value
            if not isinstance(value, ReferenceExpr):
                continue
            path = self._build_access_path(value.expr)
            if path is None:
                continue
            out.append(_SpawnBorrow(
                key=id(value), kind='argument', name=path[0],
                mutable=bool(value.mutable),
                line=value.line or spawn_expr.line,
                column=value.column or spawn_expr.column))
        return out

    def _check_spawn_borrow_order(self, spawn_expr, sources) -> set:
        """A spawn borrow of a binding declared AFTER its group is an error
        (DF-188c case i, design 188 unit 5; extended to reference ARGUMENTS by
        design 201).

        A task borrowing from its spawner is structured concurrency's core
        promise, not a hazard, and the blanket refusal was considered and
        REJECTED. The soundness argument is the ORDER: the group's `Deinit`
        joins its children at scope exit, and LIFO destruction runs it before
        anything declared AHEAD of the group dies — so a capture of an earlier
        binding is sound by construction.

        Declared AFTER the group, that argument inverts. LIFO runs the later
        binding's deinit FIRST, while the group has not joined yet, so the task
        writes into a `Vector` whose buffer is already freed. Probed Aug 9 with
        an instrumented build: the task's pushes print after "scope ends", into
        freed storage, exit 0. A silent use-after-free in safe code.

        The rule is the same invariant said in SOURCE: the group opens the scope
        it governs, so it is declared at the top of it. Hoisting the join to the
        closing brace instead was considered and declined — it deadlocks the
        drop-to-terminate idioms, whose whole point is a guard declared after
        the group whose deinit is what lets the tasks finish.

        Design 201 brings the reference ARGUMENT under the same rule, and it had
        to: probed Aug 10 with the confinement refusal lifted, a `&var buf` whose
        root is declared after the group compiled and the task pushed into `buf`
        AFTER the enclosing scope had ended, exit 0 (DF-201a). The argument
        position is not reached by the capture walk — nothing about the LIFO
        argument is different there, only the spelling.

        Returns the SOURCE KEYS this refused, so design 189's extent registration
        skips them: a borrow that cannot be written at all owes no extent, and
        the LIFO-teaching error is the one worth reading.
        """
        refused = set()
        if not isinstance(spawn_expr.object, Identifier):
            # A group reached through a field or a parameter has no declaration
            # order to compare against in this scope, and the borrow cannot
            # outlive it by the LIFO argument anyway.
            return refused
        group_info = self.current_scope.lookup(spawn_expr.object.name)
        if group_info is None:
            return refused
        group_name = spawn_expr.object.name
        for src in sources:
            info = self.current_scope.lookup(src.name)
            if info is None or info.binding_id <= group_info.binding_id:
                continue
            refused.add(src.key)
            verb = "capture" if src.kind == 'capture' else "pass"
            self._error(
                ErrorKind.EXCLUSIVITY_VIOLATION,
                f"cannot {verb} `{src.sigil} {src.name}` into a task: "
                f"`{src.name}` is declared AFTER the group `{group_name}` "
                f"it is spawned into (line {info.line} against line "
                f"{group_info.line}), and destruction is LIFO — "
                f"`{src.name}` is torn down BEFORE `{group_name}` joins "
                f"its children, so the task would reach it after it is gone",
                src.line, src.column,
                hint=f"declare `{src.name}` BEFORE `{group_name}` — the "
                     f"group opens the scope it governs, so everything the "
                     f"tasks borrow outlives the join. Or pass the value in "
                     f"by value / through an `Arc` instead of borrowing it"
            )
        return refused

    def _register_task_capture_borrows(self, spawn_expr, sources, refused) -> None:
        """Open a borrow of each borrowed ROOT for the spawned task's life
        (design 189 unit 1; design 201 for the argument position).

        The conflict a source may ALREADY be in was reported on the way down:
        both a capture list and a reference argument are part of the spawned
        call's access set, so `_check_call_exclusivity` has just checked each
        against every live borrow (that is how a second `[&var n]` of one root —
        or a second `f(&var n)` — is refused). What is left is to record the new
        borrow, and to leave it PENDING until the `let h =` binding that will
        carry it — a handle that never appears releases at the group's death
        instead, which is the fallback, not the norm.
        """
        from .core import TaskCaptureBorrow
        group_info = None
        group_name = None
        if isinstance(spawn_expr.object, Identifier):
            group_name = spawn_expr.object.name
            group_info = self.current_scope.lookup(group_name)
        opened = []
        for src in sources:
            if src.key in refused:
                continue
            info = self.current_scope.lookup(src.name)
            if info is None:
                continue
            opened.append(TaskCaptureBorrow(
                root_id=info.binding_id,
                root_name=src.name,
                mutable=src.mutable,
                spawn_line=src.line,
                spawn_column=src.column,
                group_id=(group_info.binding_id if group_info else None),
                group_name=group_name,
                kind=src.kind,
            ))
        self._task_borrows.extend(opened)
        self._pending_task_borrows = opened

    @staticmethod
    def _closures_in(node):
        """Every closure literal reachable from `node`, itself included."""
        import dataclasses
        from ast_nodes import structural_fields
        out = []
        stack = [node]
        seen = set()
        while stack:
            cur = stack.pop()
            if cur is None or isinstance(cur, (SawType, str, bytes)):
                continue
            if isinstance(cur, (list, tuple)):
                stack.extend(cur)
                continue
            if not dataclasses.is_dataclass(cur) or id(cur) in seen:
                continue
            seen.add(id(cur))
            if isinstance(cur, ClosureExpr):
                out.append(cur)
            for f in structural_fields(cur):
                stack.append(getattr(cur, f.name, None))
        return out

    def _erasure_compatible(self, at, pt):
        """Whether `&concrete` (or an already-erased `&any T`) fits a `&any T`
        slot (design 51). Used by overload CANDIDATE SELECTION, which runs before
        `_try_existential_arg_coercion` gets to perform the erasure."""
        if (at is None or pt is None
                or pt.kind != TypeKind.REFERENCE or at.kind != TypeKind.REFERENCE
                or pt.inner_type is None or at.inner_type is None
                or pt.inner_type.kind != TypeKind.EXISTENTIAL):
            return False
        if pt.reference_mutable and not at.reference_mutable:
            return False
        trait_name = pt.inner_type.existential_trait
        inner = at.inner_type
        if inner.kind == TypeKind.EXISTENTIAL:
            return inner.existential_trait == trait_name
        conc_name = inner.struct_name if inner.kind == TypeKind.STRUCT else (
            "String" if inner.kind == TypeKind.STRING else None)
        return (conc_name is not None
                and self.namespace.type_conforms_to(conc_name, trait_name))

    def _try_existential_arg_coercion(self, arg, arg_type, expected_type):
        """Coerce `&concrete -> &any Trait` at a call boundary (design 51). Returns
        True if this argument slot is an existential-reference target (whether the
        coercion succeeded or a conformance error was reported), so the caller
        skips the generic type-mismatch path."""
        if (expected_type is None or expected_type.kind != TypeKind.REFERENCE
                or expected_type.inner_type is None
                or expected_type.inner_type.kind != TypeKind.EXISTENTIAL):
            return False
        trait_name = expected_type.inner_type.existential_trait
        if arg_type is None:
            return True
        if arg_type.kind != TypeKind.REFERENCE or arg_type.inner_type is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"expected `&any {trait_name}`; pass a reference to a conforming "
                f"value (e.g. `&value`)",
                arg.value.line, arg.value.column)
            return True
        # `&var any` needs a `&var` borrow; `&any` accepts either.
        if expected_type.reference_mutable and not arg_type.reference_mutable:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`&var any {trait_name}` requires a mutable borrow (`&var value`)",
                arg.value.line, arg.value.column)
            return True
        # Already erased: forwarding a received `&any T` / `&var any T` onward as a
        # re-borrow (design 106). There is nothing to erase — the fat pointer is
        # passed through — so accept it here rather than treating the existential
        # as a "concrete" type that fails the conformance lookup below.
        if arg_type.inner_type.kind == TypeKind.EXISTENTIAL:
            if arg_type.inner_type.existential_trait != trait_name:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"expected `&any {trait_name}` but got "
                    f"`&any {arg_type.inner_type.existential_trait}`",
                    arg.value.line, arg.value.column)
            return True
        conc = arg_type.inner_type
        if self._reject_primitive_erasure(conc, trait_name,
                                          arg.value.line, arg.value.column):
            return True
        conc_name = conc.struct_name if conc.kind == TypeKind.STRUCT else (
            "String" if conc.kind == TypeKind.STRING else None)
        if conc_name is None or not self.namespace.type_conforms_to(conc_name, trait_name):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{conc}` does not conform to `{trait_name}`, so `&{conc}` cannot "
                f"be erased to `&any {trait_name}`",
                arg.value.line, arg.value.column)
            return True
        arg.value.erase_to_trait = trait_name
        arg.value.erase_concrete = conc
        return True

    def _reject_primitive_erasure(self, conc, trait_name, line, column) -> bool:
        """DF-169d: erasing a PRIMITIVE to an existential is one clean error.

        A primitive has no boxed representation to carry a vtable beside it, so
        `&any Trait` has nothing to point at. That was three different outcomes
        before — `Int`/`Float` reported "does not conform" (the conformance was
        real, the existential path just never saw it), `String` reached codegen
        and died there on `i8* != i8**`, and the fixed-width integers could not
        declare a conformance at all — for one underlying reason.

        Both ways out work TODAY and neither costs anything at runtime: a
        generic bound monomorphizes, and a wrapper struct is a nominal type with
        a real layout. Boxing stays additive later; if it lands, this error
        simply becomes working code.
        """
        name = self.namespace.primitive_conformance_key(conc)
        if name is None:
            return False
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"`{name}` is a primitive and cannot be erased to "
            f"`any {trait_name}`: an existential carries a vtable beside the "
            f"value, and a primitive has no boxed form to carry one",
            line, column,
            hint=f"take it through a generic BOUND instead — "
                 f"`<T: {trait_name}>` monomorphizes and costs nothing at "
                 f"`T = {name}` — or wrap it in a struct you own and conform "
                 f"that")
        return True

    def _check_array_method(self, expr: MethodCall, arr_type: SawType) -> Optional[SawType]:
        """Builtin members on a fixed array `[T; N]` (design 72 L12/M1).

        `.len()` — the compile-time constant length N as an `Int` (no arguments).
        `.swap(i, j)` — the M1 escape hatch: a bounds-checked in-place swap of two
        elements (mirrors `Vector.swap`), so a dynamic-index exclusivity conflict
        can be sidestepped without copying elements. `swap` mutates, so the
        receiver must be a mutable binding. No other methods exist on array types
        (user extensions on array types are a parse-level rejection)."""
        if expr.method_name == "len":
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`len` takes no arguments",
                    expr.line, expr.column)
            expr.array_builtin = "len"
            result = SawType(TypeKind.INT)
            expr.resolved_type = result
            return result
        if expr.method_name == "swap":
            # `swap` mutates in place — reject an immutable-array receiver.
            recv = expr.object
            if isinstance(recv, Identifier):
                info = self.current_scope.lookup(recv.name)
                is_var_ref = (info is not None and info.type is not None
                              and info.type.kind == TypeKind.REFERENCE
                              and info.type.reference_mutable)
                if info is not None and not info.mutable and not is_var_ref:
                    self._error(
                        ErrorKind.IMMUTABLE_ASSIGNMENT,
                        f"cannot call `swap` on immutable array `{recv.name}`",
                        expr.line, expr.column,
                        hint="consider using `var` instead of `let` to make it mutable")
            if len(expr.arguments) != 2:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`swap` takes two index arguments, got {len(expr.arguments)}",
                    expr.line, expr.column)
                result = SawType(TypeKind.VOID)
                expr.resolved_type = result
                return result
            for arg in expr.arguments:
                at = self._check_expression(arg.value)
                if at is not None and at.kind != TypeKind.INT:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`swap` index must be `Int`, got `{at}`",
                        expr.line, expr.column)
                # Reject out-of-range compile-time constant indices, mirroring
                # `a[const]`. Dynamic indices get a runtime bounds check in codegen.
                if (isinstance(arg.value, IntLiteral)
                        and arr_type.array_size is not None
                        and (arg.value.value < 0
                             or arg.value.value >= arr_type.array_size)):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`swap` index {arg.value.value} out of range for array "
                        f"with {arr_type.array_size} elements",
                        expr.line, expr.column)
            expr.array_builtin = "swap"
            result = SawType(TypeKind.VOID)
            expr.resolved_type = result
            return result
        self._error(
            ErrorKind.UNDEFINED_FUNCTION,
            f"fixed array `{arr_type}` has no method `{expr.method_name}`",
            expr.line, expr.column,
            hint="only `.len()` and `.swap(i, j)` are available on arrays; "
                 "user extensions on array types are not supported")
        return None

    def _check_enum_from_raw(self, expr, enum_info) -> Optional[SawType]:
        """Check `E.from(raw: <int>)` on a raw-backed enum (design 145 unit B2).

        The total direction is the `as` cast; this is the partial inverse, so it
        yields `E?`. Returning an optional rather than trapping is the point:
        the caller is usually decoding bytes it did not write, and an
        unrecognized tag is a fact about the input, not a bug in the program.
        It is a LOOKUP, not a constructor — unit B's no-inits-on-enums rule
        stands."""
        # Design 144: the identity, so a backed enum's `from(raw:)` reaches its
        # OWN tag table when two modules each declare one.
        enum_name = self._sym_identity(enum_info, expr.object.name)
        raw_type = enum_info.raw_type
        if len(expr.arguments) != 1:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{enum_name}.from` takes exactly one argument, "
                f"got {len(expr.arguments)}",
                expr.line, expr.column,
                hint=f"call it as `{enum_name}.from(raw: <{raw_type}>)`"
            )
            return None
        arg = expr.arguments[0]
        label = getattr(arg, 'name', None)
        if label is not None and label != "raw":
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{enum_name}.from` takes its argument labeled `raw`, "
                f"got `{label}`",
                expr.line, expr.column
            )
            return None
        arg_type = self._check_expression(arg.value)
        if arg_type is None:
            return None
        # design 205: (source, target) — the wire byte flows INTO the backing
        # type, and only that direction may widen. Written the other way round,
        # a platform `Int` reached a `UInt8` backing unchecked.
        if not self._transfer_compatible(arg_type, raw_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{enum_name}.from` expects `{raw_type}` (the enum's backing "
                f"type), got `{arg_type}`",
                expr.line, expr.column,
                hint=self._int_conversion_hint(arg_type, raw_type)
            )
            return None
        # Stamp for codegen: this lowers to a tag lookup, not a call.
        expr.enum_from_raw = enum_name
        # DF-232i: a GENERIC raw-backed enum's `from` is written on an
        # INSTANTIATION (`Code<Int>.from(raw: b)`), and the result is that
        # instantiation — carrying the arguments is what lets codegen reach the
        # monomorphized tag table. Without them the result typed as the bare
        # `Code` and codegen raised `KeyError: 'Code'`, since only
        # `Code$1$Int` is ever registered.
        type_args = [self._resolve_type(ta)
                     for ta in (getattr(expr.object, 'type_args', None) or [])]
        return SawType(TypeKind.OPTIONAL,
                       inner_type=SawType(TypeKind.ENUM, enum_name=enum_name,
                                          type_args=type_args or None))

    def _check_method_call(self, expr: MethodCall) -> Optional[SawType]:
        """Check a method call, static method call, enum initialization, or module function call."""
        # design 189: `h.join()` is the release point for every capture borrow
        # the handle carries. Join is consuming (it takes the result out of the
        # cell exactly once), so the point is statically known — which is what
        # keeps the spawn-join-use order legal without any annotation. A handle
        # reached through a field or an element is not this shape and keeps its
        # borrow to group death, the conservative edge design 189 chose.
        if (expr.method_name == "join" and self._task_borrows
                and isinstance(expr.object, Identifier)):
            self._release_task_borrows_for_handle(expr.object.name)
        # design 242 ruling 5, THREE entries into the must-consume funnel, all
        # here because all three are shaped as a method call (see `types.py`):
        #   * `Thread.spawn { ... }.join()` — the blessed chained consume. Noted
        #     BEFORE the receiver is checked, because that is what mints the
        #     obligation the chain discharges.
        if self._spawn_form_of(expr.object) is not None and expr.method_name in (
                self._SINGLETON_SPAWN_FORMS.get(expr.object.name, ())):
            self._chained_spawn_consumes.add(id(expr.object))
        #   * `h.join()` / `h.detach()` / `h.cancel()` on a bound handle.
        if self._spawn_obligations and isinstance(expr.object, Identifier):
            self._consume_spawn_obligation(expr.object.name, expr.method_name)
        #   * ruling 9a's storage discharge through a method that STORES:
        #     `self.crew.push(move t)`, std's own worker pool.
        if self._spawn_obligations:
            self._discharge_spawn_obligation_into_storage(
                expr.object, [a.value for a in (expr.arguments or [])])
        # design 51: erased-direct `Box<any Trait>.make(v)` — intercept before the
        # normal generic Box static-factory path (which would substitute the
        # unsized `any Trait` for `T` and reject the concrete argument).
        if (isinstance(expr.object, Identifier) and expr.object.name == "Box"
                and getattr(expr.object, 'type_args', None)
                and expr.object.type_args[0].kind == TypeKind.EXISTENTIAL
                and expr.method_name in ("make", "try_make")):
            return self._check_erased_box_make(expr, expr.object.type_args[0])
        # design 52b item 2: `group.spawn(f(args))` on a TaskGroup receiver. Peek
        # the receiver type (a bare identifier / member — the group local) and
        # route to the spawn handler, which records the spawn root and yields
        # `Task<T>`. Distinct from the 21b `Thread.spawn { closure }` FunctionCall.
        if expr.method_name == "spawn" and isinstance(
                expr.object, (Identifier, MemberAccess)):
            recv_t = self._check_expression(expr.object)
            if (recv_t is not None and recv_t.kind == TypeKind.STRUCT
                    and recv_t.struct_name == "TaskGroup"):
                return self._check_taskgroup_spawn(expr, recv_t)
        if isinstance(expr.object, MemberAccess):
            obj_type = self._check_member_access(expr.object)
            # DF-236a: the two arms below are the QUALIFIED-TYPE routes
            # (`module.Struct.static()`, `module.Color.Variant(...)`), and a
            # receiver they accept is spelled where a value could be. They used
            # to decide on the member access's TYPE alone — "this resolves to a
            # struct that has a static of this name" — which is equally true of
            # a member access that NAMES the type and of a FIELD READ that
            # yields a value of it. So `h.inner.solo(3)` was routed as though
            # `h.inner` were the type: the receiver was dropped and the
            # arguments shifted by one (a nullary static silently succeeded; an
            # arity-1 one reached codegen and failed the verifier), and
            # `h.color.Custom(r: 3)` built an enum value off a value receiver.
            # `names_type` is the question the type could not answer; a receiver
            # that yields a VALUE falls through to the instance path below,
            # where DF-217q's refusal and the ordinary no-such-method
            # diagnostics live. Codegen already asked the same question
            # (`resolved_struct_name`), which is why the mismatch surfaced there.
            names_type = getattr(expr.object, 'names_type', False)
            # Handle static method calls on module-qualified structs: module.Struct.method()
            if names_type and obj_type and obj_type.kind == TypeKind.STRUCT:
                struct_name = obj_type.struct_name
                struct_info = self.get_struct_info(struct_name, from_type=obj_type)
                if struct_info and expr.method_name in struct_info.methods:
                    method_info = struct_info.methods[expr.method_name]
                    if method_info.is_static:
                        # design 256: this route used to take the lone
                        # representative and consult no overload set AT ALL,
                        # while its BARE twin below resolved one — which is
                        # exactly why only the qualified spelling of
                        # `mod.Bag.make(from:, bump:)` was refused.
                        return self._check_resolved_static_call(
                            expr, struct_name, struct_info, method_info)
                    elif method_info.is_init:
                        # design 27 item 3: an `init` reached through the
                        # member-access form (`pkg.Struct.init(...)`) is not the
                        # supported call syntax — custom initializers are invoked
                        # as `pkg.Struct(...)` (which flows through
                        # `_check_module_struct_init`). In practice this branch is
                        # unreachable: `init` is a keyword so it never parses as a
                        # method name, and init symbols live in `init_methods`, not
                        # the `methods` dict. Emit a clean diagnostic rather than
                        # calling into a nonexistent handler if it is ever reached.
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot call initializer of `{struct_name}` this way",
                            expr.line, expr.column,
                            hint=f"construct it directly as `{struct_name}(...)`"
                        )
                        return SawType(TypeKind.STRUCT, struct_name=struct_name,
                                       symbol=struct_info)
            # Handle module-qualified enum variant construction: lib.Color.Custom(r: 1, g: 2, b: 3)
            if names_type and obj_type and obj_type.kind == TypeKind.ENUM:
                enum_info = self.get_enum_info(obj_type.enum_name, from_type=obj_type)
                if enum_info and expr.method_name in enum_info.variants:
                    enum_init = EnumInit(
                        enum_name=obj_type.enum_name,
                        variant_name=expr.method_name,
                        arguments=expr.arguments,
                        type_args=obj_type.type_args,
                        enum_symbol=enum_info,  # Pass symbol for module-qualified lookup
                        line=expr.line,
                        column=expr.column
                    )
                    # Attach to AST so codegen can use it
                    expr.resolved_enum_init = enum_init
                    return self._check_enum_init(enum_init)
                # design 256: the qualified ENUM's STATIC route, which did not
                # exist — the arm above answered VARIANTS only, so
                # `mod.Tone.of(seed: 1)` fell through to the instance path and
                # came back as DF-217q's "cannot be called on a value" for a
                # call that names the type. Mirrors the bare enum arm below,
                # including its ordering: a case always wins a name clash, so a
                # static gets first refusal only where no variant answers.
                if (enum_info and expr.method_name not in enum_info.variants
                        and expr.method_name in enum_info.methods):
                    static_info = enum_info.methods[expr.method_name]
                    if static_info.is_static:
                        return self._check_resolved_static_call(
                            expr, obj_type.enum_name, enum_info, static_info)
            if obj_type and obj_type.kind == TypeKind.MODULE:
                inner_module_sym = getattr(expr.object, 'resolved_module_symbol', None)
                if inner_module_sym and inner_module_sym.namespace:
                    from namespace import SymbolKind
                    # DF-232j: `self.namespace.module_path` is the module whose
                    # namespace is loaded, which the std-leaf case makes wrong;
                    # `_accessor_vis_module` is the module of the code being
                    # checked. A refused reach reports the TIER.
                    refusals = []
                    symbol = inner_module_sym.namespace.resolve(
                        expr.method_name,
                        check_visibility=True,
                        accessor_module=self._accessor_vis_module(),
                        through_import=True, refusals=refusals
                    )
                    if symbol is None:
                        surface_hint = self._not_reexported_hint(
                            inner_module_sym.namespace, expr.method_name,
                            obj_type.module_name)
                        if self._report_visibility_refusal(
                                refusals, expr.line, expr.column,
                                surface_hint):
                            self._check_arguments_anyway(expr)  # DF-232p
                            return None
                        self._error(
                            ErrorKind.UNDEFINED_FUNCTION,
                            f"module `{obj_type.module_name}` has no function `{expr.method_name}`",
                            expr.line, expr.column,
                            hint=surface_hint
                        )
                        self._check_arguments_anyway(expr)  # DF-232p
                        return None
                    if symbol.kind == SymbolKind.FUNCTION:
                        # Overloading (design 55): resolve against the module's
                        # overload set when it has 2+ members.
                        mo = inner_module_sym.namespace.lookup_function_overloads(
                            expr.method_name)
                        if len(mo) > 1:
                            return self._check_overloaded_module_function_call(expr, mo)
                        # Use the symbol directly - it's already a FunctionSymbol
                        return self._check_module_function_call(expr, symbol)
                    elif symbol.kind == SymbolKind.STRUCT:
                        # For module-qualified struct init, check using the symbol directly
                        return self._check_module_struct_init(expr, symbol)
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"`{expr.method_name}` is not callable",
                            expr.line, expr.column
                        )
                        self._check_arguments_anyway(expr)  # DF-232p
                        return None
        if isinstance(expr.object, Identifier):
            # Design 150 pin 4: a value binding of this name wins; the qualifier
            # is consulted last.
            module_sym = self._module_qualifier(expr.object.name)
            if module_sym and module_sym.namespace:
                from namespace import SymbolKind
                # DF-232j: see the chained arm above.
                refusals = []
                symbol = module_sym.namespace.resolve(
                    expr.method_name,
                    check_visibility=True,
                    accessor_module=self._accessor_vis_module(),
                    through_import=True, refusals=refusals
                )
                if symbol is None:
                    surface_hint = self._not_reexported_hint(
                        module_sym.namespace, expr.method_name,
                        expr.object.name)
                    if self._report_visibility_refusal(
                            refusals, expr.line, expr.column, surface_hint):
                        self._check_arguments_anyway(expr)  # DF-232p
                        return None
                    self._error(
                        ErrorKind.UNDEFINED_FUNCTION,
                        f"module `{expr.object.name}` has no function `{expr.method_name}`",
                        expr.line, expr.column,
                        hint=surface_hint
                    )
                    self._check_arguments_anyway(expr)  # DF-232p
                    return None
                if symbol.kind == SymbolKind.FUNCTION:
                    # Overloading (design 55): resolve against the module's
                    # overload set when it has 2+ members.
                    mo = module_sym.namespace.lookup_function_overloads(
                        expr.method_name)
                    if len(mo) > 1:
                        return self._check_overloaded_module_function_call(expr, mo)
                    # Use the symbol directly - it's already a FunctionSymbol
                    return self._check_module_function_call(expr, symbol)
                elif symbol.kind == SymbolKind.STRUCT:
                    # For module-qualified struct init, check using the symbol directly
                    return self._check_module_struct_init(expr, symbol)
                elif symbol.kind == SymbolKind.ENUM:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"use `{expr.object.name}.{expr.method_name}.Variant(...)` to create enum values",
                        expr.line, expr.column
                    )
                    self._check_arguments_anyway(expr)  # DF-232p
                    return None
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`{expr.method_name}` is not callable",
                        expr.line, expr.column
                    )
                    self._check_arguments_anyway(expr)  # DF-232p
                    return None
        if isinstance(expr.object, Identifier):
            # Prelude discipline (design 82 Part B): a bare `TcpStream.connect(...)`
            # on a non-prelude std type not imported here errors with an import
            # hint, before it resolves to the hidden static method.
            if (expr.object.name in getattr(self, '_std_symbol_file', {})
                    and self._std_name_gated(
                        expr.object.name, expr.line, expr.column)):
                return None
            struct_info = self.get_struct_info(expr.object.name)
            if struct_info:
                struct_name = expr.object.name
                if expr.method_name in struct_info.methods:
                    method_info = struct_info.methods[expr.method_name]
                    if method_info.is_static:
                        # Overloading (design 55): resolve among static
                        # overloads, through design 256's funnel so the set is
                        # the RESOLVED receiver's rather than a re-resolution of
                        # the written name.
                        return self._check_resolved_static_call(
                            expr, struct_name, struct_info, method_info)
        if isinstance(expr.object, Identifier) and self.get_enum_info(expr.object.name):
            # Design 145: a STATIC method on the enum gets first refusal —
            # otherwise `SysError.from(raw: b)` is read as a variant named
            # `from` and reported as "enum has no variant". A case always wins a
            # name clash: cases are the enum's own vocabulary, and a static
            # method is the newcomer.
            enum_info = self.get_enum_info(expr.object.name)
            if (expr.method_name not in enum_info.variants
                    and expr.method_name in enum_info.methods):
                static_info = enum_info.methods[expr.method_name]
                if static_info.is_static:
                    return self._check_resolved_static_call(
                        expr, expr.object.name, enum_info, static_info)
            # Design 145 unit B2: the synthesized inverse of the `as` cast.
            # `E.from(raw: u)` is a LOOKUP, not a constructor — an unrecognized
            # value is DATA (a bad wire byte), never a trap, so it returns `E?`
            # and `None` means "no case has that value". Ranks below a case name
            # and below a user-written static of the same name.
            if (expr.method_name == "from"
                    and expr.method_name not in enum_info.variants
                    and expr.method_name not in enum_info.methods
                    and getattr(enum_info, 'raw_type', None) is not None):
                return self._check_enum_from_raw(expr, enum_info)
            expr.resolved_type_identity = self._sym_identity(
                enum_info, expr.object.name)
            enum_init = EnumInit(
                enum_name=expr.resolved_type_identity,
                variant_name=expr.method_name,
                arguments=expr.arguments,
                type_args=expr.object.type_args,
                line=expr.line,
                column=expr.column
            )
            return self._check_enum_init(enum_init)
        # Design 170: `UInt8.from(x)` / `UInt8.from(truncating: x)`. An integer
        # type name is not a value, so this must be answered before the receiver
        # is checked as an expression — otherwise it reports `undefined variable
        # UInt8` and the real call never resolves.
        if (isinstance(expr.object, Identifier)
                and expr.method_name == "from"
                and expr.object.name in self._INT_LIMIT_TYPE_KINDS):
            return self._check_int_from(expr)
        obj_type = self._check_expression(expr.object)
        if obj_type is None:
            return None

        # design 51: dynamic dispatch through an erased receiver (`any T`,
        # `&any T`, or `Box<any T>`) — resolve against the trait signature.
        recv_trait = self._existential_receiver_trait(obj_type)
        if recv_trait is not None:
            return self._check_existential_method_call(expr, obj_type, recv_trait)

        # design 46: accessors on `UnsafeMemory<T, Use>` — `read()`/`write(v)`
        # (Device: volatile, scalar-only, RO/WO gated) and the Normal region
        # accessors `ptr()`/`len()`/`end()`.
        if self._is_unsafe_memory(obj_type):
            return self._check_um_method(expr, obj_type)

        # design 186: `ptr()` on an `UnsafeMutableInterior<T>` — the cell's ONE
        # accessor, and its whole safety story. Compiler-known for the same
        # reason `UnsafeMemory`'s accessors are: the cell is layout-transparent,
        # so there is no `self.value` to project — the receiver's storage IS the
        # `T`, and the address of that storage is what the caller asked for.
        cell_payload = self.namespace.cell_payload(obj_type)
        if cell_payload is not None:
            return self._check_interior_cell_method(expr, cell_payload)

        # `.copy()` — the umbrella Copy operation. Handles auto-Copy of trivial
        # types and `.copy()` through a `T: Copy`-family bound. Types that carry
        # a real copy() method (Copy/ExplicitCopy) fall through to normal
        # method dispatch.
        if expr.method_name == "copy" and len(expr.arguments) == 0:
            handled, result = self._check_copy_call(expr, obj_type)
            if handled:
                return result

        # `.hash(&h)` — the Hashable streaming operation (design 48). A receiver
        # with a real `hash` method (String, or a struct with a synthesized /
        # custom hash) dispatches normally; a primitive or an auto-conforming
        # (POD struct / payload-free enum) receiver is resolved here.
        if expr.method_name == "hash" and len(expr.arguments) == 1:
            handled, result = self._check_hash_call(expr, obj_type)
            if handled:
                return result

        # `.to_string()` / `.format(into:)` — the Printable operations (design 56).
        # A user struct conforming to Printable carries real methods (its
        # hand-written `format` and its synthesized `to_string`) and dispatches
        # normally; a builtin (primitive / String) receiver is resolved here and
        # emitted inline by codegen. A generic `T` is left to the bound resolver.
        if (expr.method_name in ("to_string", "format")):
            handled, result = self._check_printable_call(expr, obj_type)
            if handled:
                return result

        # Bound-aware method resolution on an opaque generic type parameter
        # (design 24 item 1). Inside a generic body, `x.method()` where `x: T`
        # resolves against the methods declared by T's trait bounds; a method
        # found in a bound's trait is checked against that signature (associated
        # types stay abstract), and a method found in no bound is an error naming
        # the method and the bounds. `.copy()` under a `Copy`-family bound was
        # already resolved above.
        type_params = getattr(self, 'current_type_params', {})
        if obj_type.kind == TypeKind.STRUCT and obj_type.struct_name in type_params:
            return self._check_type_param_method_call(
                expr, obj_type, type_params[obj_type.struct_name])

        # Builtin members on a fixed array `[T; N]` (design 72 L12/M1). User
        # extensions on array types are unsupported (a parse-level rejection);
        # the whole surface is `.len()` and `.swap(i, j)`. `.copy()` was already
        # routed above through the Copy machinery.
        if obj_type.kind == TypeKind.ARRAY:
            return self._check_array_method(expr, obj_type)

        # `o.take()` — the consuming payload read (design 131). Swaps `None` into
        # the place and hands the payload back owned, so it works on any
        # `&var`-reachable place INCLUDING a FIELD, which is the move-out that
        # no-partial-moves otherwise forbids.
        if (obj_type.kind == TypeKind.OPTIONAL
                and expr.method_name == "take"
                and not getattr(expr, 'type_args', None)):
            return self._check_optional_take(expr, obj_type)

        # `o.is_some()` / `o.is_none()` — the tag-only presence reads (DF-218a).
        if (obj_type.kind == TypeKind.OPTIONAL
                and expr.method_name in ("is_some", "is_none")
                and not getattr(expr, 'type_args', None)):
            return self._check_optional_presence(expr, obj_type)

        _prim_ext_name = self.namespace.primitive_conformance_key(obj_type)
        if _prim_ext_name is not None:
            # Method on a primitive pseudo-struct (design 57, every primitive
            # since design 176 / DF-169d).
            struct_name = _prim_ext_name
            struct_info = self.get_struct_info(struct_name)
        elif obj_type.kind == TypeKind.STRUCT:
            struct_name = obj_type.struct_name
            struct_info = self.get_struct_info(struct_name, from_type=obj_type)
            if struct_info is None and self.get_enum_info(struct_name) is not None:
                # A bare type name parses STRUCT-kinded; a reference parameter
                # (`l: &Level`) can reach here still carrying that kind for what
                # is really an enum. Codegen re-tags the same way (design 61).
                # Without this the receiver resolves to nothing and the call
                # types as None with no diagnostic at all.
                struct_info = self.get_enum_info(struct_name)
        elif obj_type.kind == TypeKind.ENUM:
            # Design 145: enums carry methods on the same terms as structs, and
            # `EnumSymbol` carries the same method tables, so everything below
            # (lookup, the design-80 gate, the design-55 overload resolver, the
            # design-142 ambiguity check) works against it unchanged.
            struct_name = obj_type.enum_name
            struct_info = self.get_enum_info(struct_name)
        else:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot call method on non-struct type `{obj_type}`",
                expr.line, expr.column
            )
            return None
        if struct_name is None or struct_info is None:
            return None
        type_subst: Dict[str, SawType] = {}
        if struct_info.type_params and obj_type.type_args:
            for type_param, type_arg in zip(struct_info.type_params, obj_type.type_args):
                type_subst[type_param.name] = type_arg

        # Look up method - first check specialized extensions, then generic
        method_info = self._lookup_method(struct_info, expr.method_name, obj_type.type_args)
        # DF-216h: fold in the owning extension's aliases for the same
        # positions (a no-op unless the extension renames). Done here, off the
        # representative, so the design-55 resolver below sees a substitution
        # that can match a renamed candidate's parameter types; the winner's
        # own aliases are re-folded in `_check_overloaded_method_call`.
        if type_subst and method_info is not None:
            self._receiver_type_subst(struct_info, obj_type.type_args,
                                      method_info, type_subst)
        # DF-217q: a STATIC method is not reachable through an INSTANCE. It has
        # no `self`, so the receiver has nowhere to go: the call-site parameter
        # offset sliced a slot the callee does not have, every label lined up
        # against the wrong parameter, and where they happened to bind anyway
        # codegen passed the receiver as argument 0 and failed the verifier.
        # Ruled a clean refusal rather than a binding fix — the type spelling is
        # the one way to call one, and an instance path would give the same
        # method two call shapes with no gain.
        if method_info is not None and getattr(method_info, 'is_static', False):
            instance_alt = self._instance_method_alternative(
                struct_info, expr.method_name)
            if instance_alt is None:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{expr.method_name}` is a static method of "
                    f"`{struct_name}` and cannot be called on a value",
                    expr.line, expr.column,
                    hint=f"call it on the type: "
                         f"`{struct_name}.{expr.method_name}(...)`. A static "
                         f"method has no `self`, so there is nothing for the "
                         f"receiver to become")
                return None
            # A static and an instance method may share a name; the instance
            # call resolves to the instance one and the static is simply not a
            # candidate here.
            method_info = instance_alt
        # Member visibility (design 80): gate a directly-resolved instance method
        # (before the Arc/Box payload-forward fallbacks, which are a separate
        # mechanism keyed on the payload type's own access).
        if method_info is not None:
            self._check_method_visible(struct_name, expr.method_name, method_info, expr)
            # design 219 wave C: discharge entry point 3 — the RECEIVER's type
            # arguments. A method of `extension Wrap<T>` that duplicates its
            # `T` is DF-217i at a second position (S1 row 12), and the type
            # parameter it constrains belongs to the extension, not the call.
            if type_subst and struct_info.type_params:
                self._tier_record_obligation(
                    method_info.ast_node, struct_info.type_params, type_subst,
                    f"`{struct_name}.{expr.method_name}`", expr.line,
                    expr.column)
        # Overloading (design 55): a method name with 2+ overloads on this struct
        # resolves through the exact-match resolver (before effect edges are
        # recorded), then feeds the shared downstream machinery.
        if method_info is not None:
            # DF-217q: statics are not candidates for an INSTANCE call, so they
            # never reach the resolver — a mixed set resolves among the instance
            # methods alone rather than letting a static win on arity.
            method_overloads = [
                m for m in self._receiver_method_overloads(
                    struct_info, expr.method_name)
                if not getattr(m, 'is_static', False)]
            if len(method_overloads) > 1:
                # Design 142: two visible extensions of one type may share a name
                # (they resolve by the ordinary overload rules), but a
                # signature-identical pair from two modules is unresolvable here.
                clash = self._first_cross_module_method_clash(method_overloads)
                if clash is not None:
                    a, b = clash
                    self._error(
                        ErrorKind.DUPLICATE_FUNCTION,
                        f"ambiguous method `{expr.method_name}` on `{struct_name}`: "
                        f"`{self._module_label(a.def_module)}` and "
                        f"`{self._module_label(b.def_module)}` both extend it with "
                        f"an indistinguishable signature",
                        expr.line, expr.column,
                        hint="import only one of the two modules here, or move the "
                             "call into a file that sees a single definition")
                    return None
                return self._check_overloaded_method_call(
                    expr, struct_name, method_overloads, obj_type, type_subst)
            # Design 142: a method can carry a module-discriminated codegen
            # symbol while only ONE of its overloads is visible here — the other
            # lives in a module this file does not import. The overload path
            # never runs, so stamp the resolved symbol ourselves; without it
            # codegen would mangle the plain name and find no definition.
            if getattr(method_info, 'mangled_name', ''):
                expr.resolved_symbol = method_info.mangled_name
        # Arc payload access via method forwarding (design 21b E2). When a method
        # is not found on `Arc<T>` itself but exists on the payload `T` with an
        # immutable `&self` receiver, forward the call to the payload through an
        # immutable borrow of the control block's payload slot. This is sound: a
        # live strong reference pins the payload, so a shared read cannot dangle.
        # A `&var self` payload method is REJECTED — aliased mutation through a
        # shared `Arc` is exactly what `Mutex` exists to make safe.
        if method_info is None and struct_name == "Arc" and obj_type.type_args:
            fwd = self._resolve_arc_forward(expr, obj_type.type_args[0])
            if fwd == "rejected":
                return None
            if fwd is not None:
                method_info, type_subst = fwd
                expr.arc_forward_payload_type = obj_type.type_args[0]
        # Box payload forwarding (design 42 item 1): same mechanism as Arc — an
        # immutable `&self` payload method is callable through the Box, borrowing
        # the heap `T` at `ptr[0]`; a `&var self` payload method is REJECTED. The
        # payload is the FIRST type arg (`Box<T, A>`); `A` is the allocator.
        if method_info is None and struct_name == "Box" and obj_type.type_args:
            fwd = self._resolve_arc_forward(expr, obj_type.type_args[0], through="Box")
            if fwd == "rejected":
                return None
            if fwd is not None:
                method_info, type_subst = fwd
                expr.box_forward_payload_type = obj_type.type_args[0]
        # design 218 unit 3 (the slice unit 1.5 pulled forward, user ruling
        # Sep 1) — an Equatable/Comparable REQUIREMENT on a receiver whose
        # conformance body lives in CODEGEN. Asked before the `method_info is
        # None` refusal below because ONE member of that set does have a
        # same-named method: `String`'s own by-value API.
        requirement = self._builtin_requirement_call(expr, obj_type, method_info)
        if requirement is not None:
            return requirement
        if method_info is None:
            # A call through a function-typed struct field: `obj.field(args)`
            # where `field: (…) -> …` (design 24 item 3). Treated as an indirect
            # call; the field's type drives suspendability — a non-`sync` field
            # type conservatively suspends the caller.
            fields = getattr(struct_info, 'fields', None)
            field_type = fields.get(expr.method_name) if fields else None
            if field_type is not None:
                if type_subst:
                    field_type = field_type.substitute(type_subst)
                if field_type.kind == TypeKind.FUNCTION:
                    return self._check_field_call(expr, field_type)
                # design 226: the same, one wrapper out. A dispatch TABLE is
                # the headline use of `FuncPointer`, and a table is a struct of
                # them — `TABLE.run(x)` is how one is read. Checked against `F`
                # by the same routine; codegen tells the two apart by the
                # field's own type.
                fp_field = self._funcpointer_signature(field_type)
                if fp_field is not None:
                    expr.funcpointer_target = field_type
                    return self._check_field_call(expr, fp_field)
                # design 77 item 4: an opt-encoded closure frame field
                # (`f: (()->Int)?` on a synthesized `__Frame_*` struct) is called
                # through `self.f` — force-unwrap to the closure and dispatch as an
                # indirect field call. Restricted to frame structs so a user's
                # optional-closure field keeps its current (non-callable) meaning.
                if (field_type.kind == TypeKind.OPTIONAL
                        and field_type.inner_type is not None
                        and field_type.inner_type.kind == TypeKind.FUNCTION
                        and struct_name.startswith("__Frame_")):
                    expr.field_call_unwrap = True
                    return self._check_field_call(expr, field_type.inner_type)
            # Design 142: the method may exist, just not here. Name the module
            # that defines it and the import that would bring it into scope —
            # otherwise the reader concludes the method is missing and writes a
            # second copy of it.
            unimported = self._out_of_scope_method_modules(
                struct_info, expr.method_name, obj_type.type_args)
            if unimported:
                mods = ", ".join(f"`{m}`" for m in unimported)
                one = unimported[0]
                self._error(
                    ErrorKind.UNDEFINED_FUNCTION,
                    f"type `{struct_name}` has no method `{expr.method_name}` "
                    f"in scope here",
                    expr.line, expr.column,
                    hint=f"{mods} extends `{struct_name}` with `{expr.method_name}`, "
                         f"but this file does not import it — add `import {one}`"
                )
                return None
            # Collect available methods from both generic and specialized,
            # excluding any this file cannot see.
            available = [n for n, sym in struct_info.methods.items()
                         if self._ext_scope_allows(sym, struct_info)]
            if obj_type.type_args:
                spec_key = self._make_specialization_key(obj_type.type_args)
                if spec_key in struct_info.specialized_methods:
                    available.extend(
                        n for n, sym in struct_info.specialized_methods[spec_key].items()
                        if self._ext_scope_allows(sym, struct_info))
            # DF-236a's enum face: `h.color.Custom(r: 3)` names a VARIANT
            # through a VALUE of the enum. A variant is a constructor, so the
            # receiver has nowhere to go — the same shape as DF-217q's static
            # refusal, and the same fix: spell the type. Reported here rather
            # than as "has no method", which sends the reader looking for a
            # method that was never the thing they wrote.
            _variants = getattr(struct_info, 'variants', None)
            if _variants is not None and expr.method_name in _variants:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{expr.method_name}` is a variant of enum `{struct_name}` "
                    f"and cannot be constructed through a value",
                    expr.line, expr.column,
                    hint=f"construct it on the type: "
                         f"`{struct_name}.{expr.method_name}(...)`. A variant "
                         f"builds a new value, so there is nothing for the "
                         f"receiver to become")
                return None
            # Design 150 pin 4: a shadowed module qualifier explains this call
            # far better than a method list does.
            shadow = self._qualifier_shadow_hint(expr.object, expr.method_name)
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"type `{struct_name}` has no method `{expr.method_name}`",
                expr.line, expr.column,
                hint=shadow or (
                    f"available methods: {', '.join(sorted(set(available)))}"
                    if available else "no methods defined")
            )
            return None
        # Conditional conformance: a method declared in a bounded extension
        # (`extension Vector<T: Copy>`) does not exist for an instantiation whose
        # type args fail the bound. Diagnose the call by naming the unmet bound.
        unmet = self._unmet_extension_bound(method_info, type_subst)
        if unmet is not None:
            param_name, bound, concrete = unmet
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"type `{obj_type}` has no method `{expr.method_name}`: "
                f"requires `{param_name}: {bound}`, and `{concrete}` does not conform",
                expr.line, expr.column,
                hint=f"`{expr.method_name}` is only available when `{param_name}` satisfies `{bound}`"
            )
            return None
        if expr.method_name == "deinit":
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot call `deinit` manually; it is called automatically when the value goes out of scope",
                expr.line, expr.column,
                hint="use a nested scope or `move` to transfer ownership if you need early cleanup"
            )
            return None
        # design 141: a named `borrows` accessor (`v.get(i)`, `v.first()`) hands
        # out a PLACE. Its window closures are compiler-added trailing
        # parameters, so the ordinary arity path below would count them against
        # the author; place checking owns the call from here.
        if (self._place_accessor_node(method_info) is not None
                and not getattr(expr, 'place_lowered', False)):
            return self._check_place_use(
                expr, method_info, struct_name, obj_type, expr.method_name,
                [a.value for a in expr.arguments])
        # Method-level generic type parameters (brief 36): fold the call-site type
        # arguments (`v.map<Int>(...)`) into the substitution map alongside the
        # struct's own args, so param/return types mentioning the method's own
        # params (`(T) -> U`, `-> Vector<U>`) resolve concretely. Design 93: an
        # omitted (or partially-omitted) argument list is INFERRED from the
        # argument types — a bare `v.map({ $0.to_string() })` solves `U` from the
        # closure's inferred return. Explicit-and-complete wins unchanged.
        if not self._fold_method_type_args(
                expr, method_info, type_subst,
                1 if not method_info.is_init else 0):
            return None
        # design 22: record the call edge to the resolved method's suspend node.
        self._effect_call_method(
            method_info, f"`{struct_name}.{expr.method_name}`", expr.line)
        param_offset = 1 if not method_info.is_init else 0
        total_params = len(method_info.param_types) - param_offset
        defaults_for_params = method_info.default_values[param_offset:] if method_info.default_values else []
        required_count = sum(1 for dv in defaults_for_params if dv is None) if defaults_for_params else total_params
        logical_names = method_info.param_names[param_offset:]
        # Design 66: labeled arguments bind by the binding rule; positional-only
        # calls keep the exact legacy arity checks and identity binding.
        has_labels = self._call_has_labels(expr)
        if has_labels:
            mapping = self._bind_args(expr, logical_names, defaults_for_params,
                                      expr.method_name)
            if mapping is None:
                return method_info.return_type
        else:
            mapping = None
            if len(expr.arguments) < required_count:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{expr.method_name}` takes at least {required_count} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return method_info.return_type
            if len(expr.arguments) > total_params:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{expr.method_name}` takes at most {total_params} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return method_info.return_type
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] if mapping is not None else i
            declared_type = method_info.param_types[p + param_offset]
            expected_type = declared_type
            if type_subst:
                expected_type = expected_type.substitute(type_subst)
            allow_wrap = self._df3_allow_wrap(
                declared_type, set(type_subst.keys()) if type_subst else None)
            # Closure arguments infer their parameter types from the expected
            # function type and may carry reference params (e.g. Mutex.lock).
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type, as_call_argument=True)
            else:
                # Design 87: the bare-literal adoption stamp, which the OTHER
                # argument paths (free function, module-qualified, static
                # method) all ran and this one — the plain instance-method
                # call — did not. `d.push(1)` on a `Data` reached the check as
                # a platform `Int` against a `UInt8` parameter, and the
                # platform-pair permission absorbed it in silence; with that
                # permission closed (design 205) the gap is a refusal of the
                # most ordinary call in the language, so it is fixed at the
                # path rather than migrated at the call sites.
                self._apply_literal_expected_type(arg.value, expected_type)
                arg_type = self._check_expression(arg.value)
            if self._try_existential_arg_coercion(arg, arg_type, expected_type):
                pass  # `&concrete -> &any Trait` erasure (or its error) handled
            elif arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type, allow_wrap):
                param_name = method_info.param_names[p + param_offset]
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column,
                    hint=self._int_conversion_hint(arg_type, expected_type)
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        # Design 40 item 6 (L11): a `&var self` method mutates its receiver, so
        # it may not be called on an immutable `let` (or `&`) binding — the same
        # rule as a `p.x = ...` field write. (`init` builds a fresh value; not a
        # receiver mutation.)
        # design 141: an EXCLUSIVE place window borrows its root mutably even
        # though the accessor declares `&self` — one body serves both flavors,
        # and the use site picks. So `let v` plus `v[0].n = 1` is the same
        # immutable-binding error a `&var self` method would give.
        window_exclusive = getattr(expr, 'place_window_exclusive', False)
        self._reject_var_self_call_on_shared_self(expr, method_info)
        # design 260: the consuming-receiver funnel, entry point 2 of 2.
        self._check_consuming_receiver(expr, method_info)
        if ((getattr(method_info, "self_mutable", False) or window_exclusive)
                and not method_info.is_init):
            imm_root = self._immutable_receiver_root(expr.object)
            if imm_root is not None:
                what = (f"open an exclusive place window on"
                        if window_exclusive
                        else f"call `&var self` method `{expr.method_name}` on")
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot {what} immutable variable `{imm_root}`",
                    expr.line, expr.column,
                    hint="consider using `var` instead of `let` to make it mutable",
                )
        # Exclusivity: the receiver of a `var self` method is a mutable path;
        # its parameter types (excluding self) align with the arguments.
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping, method_info.param_types[param_offset:], logical_names)
        self._check_call_exclusivity(
            [a.value for a in expr.arguments],
            aligned_types,
            receiver=expr.object if not method_info.is_init else None,
            receiver_mutable=method_info.self_mutable or window_exclusive,
            param_names=aligned_names,
        )
        return_type = method_info.return_type
        if type_subst:
            return_type = return_type.substitute(type_subst)
        # design 62 G3: mark a cooperative `Channel.receive()` call so the coro
        # transform lowers the call site INLINE into the try_receive+yield_now loop
        # (the method itself is never monomorphized). Its `receive` body reaches
        # `yield_now`, so the effect edge recorded above already taints the caller.
        if struct_name == "Channel" and expr.method_name == "receive":
            expr.is_chan_recv = True
        return return_type

    def _check_overloaded_module_function_call(self, expr, candidates):
        """Resolve and check a module-qualified call to an overloaded function
        (design 55). Modules are merged at codegen, so the resolved overload's
        stamped symbol is a plain global — routed via expr.resolved_symbol."""
        arg_types = self._overload_arg_types(expr)
        func_info, mapping = self._resolve_overload(
            expr.method_name, candidates, arg_types,
            self._has_explicit_type_args(expr),
            is_method=False, line=expr.line, column=expr.column,
            arguments=expr.arguments, expr=expr, base_subst={})
        if func_info is None:
            return None
        if func_info.mangled_name:
            expr.resolved_symbol = func_info.mangled_name
        self._stamp_overload_plan(expr, func_info.param_names, mapping)
        self._effect_call_function(func_info, expr.method_name, expr.line)
        param_types = func_info.param_types
        return_type = func_info.return_type
        # Design 105: a generic module-function overload selected by inference.
        if func_info.type_params:
            type_map = {}
            for tp, ta in zip(func_info.type_params, expr.type_args or []):
                type_map[tp.name] = self._resolve_type(ta)
            self._check_type_param_bounds(
                func_info.type_params, type_map, expr.line, expr.column)
            resolved_args = [type_map.get(tp.name) for tp in func_info.type_params]
            if all(a is not None and self._is_concrete_type(a)
                   for a in resolved_args):
                self._effect_record_poly_call(
                    expr.method_name, resolved_args,
                    f"`{expr.method_name}`", expr.line)
            param_types = [t.substitute(type_map) for t in param_types]
            if return_type is not None:
                return_type = return_type.substitute(type_map)
        self._finish_overloaded_args(expr, param_types, arg_types, mapping)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping if self._call_has_labels(expr) else None,
            param_types, func_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments], aligned_types,
                                     param_names=aligned_names)
        return return_type

    def _check_resolved_static_call(self, expr, type_name: str, type_info,
                                    representative):
        """A static call spelled on a TYPE, resolved over that type's whole
        in-scope static overload set (design 256).

        The ONE place the four static routes meet — bare struct, bare enum,
        module-qualified struct, module-qualified enum — so the set a call sees
        no longer depends on which of them the spelling happened to take. The
        qualified struct route consulted no set at all and the qualified enum
        route did not exist; the two bare ones re-resolved by written name,
        which is the same DF-280a lookup the instance side had.

        `representative` is `methods[name]`, the first-registered overload the
        route already had in hand. It is the answer only where design 142's
        scope filter admits nothing — no candidate is in scope, so refusing here
        would report a scope failure the diagnostics downstream are better
        placed to explain, and the route behaves exactly as it did before."""
        # Design 144: the receiver type's IDENTITY is what its method symbols
        # are mangled against, and — for a module-qualified receiver — the only
        # stamp codegen's static dispatch can read (the member access carries
        # `resolved_struct_name` for a struct alone). Stamped HERE, at the
        # funnel, so it does not depend on which of the two resolvers below
        # runs: `_check_static_method_call` set it and the OVERLOADED twin
        # never did, so a qualified static with 2+ overloads generated its
        # QUALIFIER as a receiver expression.
        expr.resolved_type_identity = self._sym_identity(type_info, type_name)
        statics = self._static_method_overloads(type_info, expr.method_name)
        if len(statics) > 1:
            return self._check_overloaded_static_method_call(
                expr, type_name, type_info, statics)
        chosen = statics[0] if statics else representative
        # The instance path's DF-142 stamp, at the static position: a symbol can
        # carry a signature- or module-discriminated codegen name while only ONE
        # candidate reaches this call — the set holds an instance sibling of the
        # same name, or a second module's copy this file does not import. The
        # overload path never runs, so the plain-name mangling codegen would
        # fall back to names no definition was emitted under.
        if getattr(chosen, 'mangled_name', ''):
            expr.resolved_symbol = chosen.mangled_name
        return self._check_static_method_call(
            expr, type_name, type_info, chosen)

    def _check_overloaded_static_method_call(self, expr, struct_name,
                                             struct_info, candidates):
        """Resolve and check an overloaded static method call (design 55):
        `StructName.method(args)` with 2+ static overloads."""
        arg_types = self._overload_arg_types(expr)
        # Build the struct type-param -> concrete map from the receiver's type
        # args (default-filled), as _check_static_method_call does, so a factory
        # whose parameters mention the struct's type params checks concretely.
        # Computed BEFORE resolution so it seeds design-105 inference (base subst).
        obj_type_args = getattr(expr.object, 'type_args', None)
        struct_type_params = getattr(struct_info, 'type_params', None)
        type_map = {}
        receiver_args = []
        if obj_type_args and struct_type_params:
            receiver_args = [self._resolve_type(ta) for ta in obj_type_args]
            receiver_args = self._append_default_type_args(struct_name, receiver_args)
            for tp, ta in zip(struct_type_params, receiver_args):
                type_map[tp.name] = ta
        method_info, mapping = self._resolve_overload(
            f"{struct_name}.{expr.method_name}", candidates, arg_types,
            self._has_explicit_type_args(expr), is_method=True,
            line=expr.line, column=expr.column,
            arguments=expr.arguments, expr=expr, base_subst=dict(type_map))
        if method_info is None:
            return None
        if method_info.mangled_name:
            expr.resolved_symbol = method_info.mangled_name
        # DF-184a: same stamp the non-overloaded path makes — see
        # `_check_static_method_call`.
        expr.is_static_method_call = True
        expr.static_receiver = struct_name
        self._stamp_overload_plan(expr, method_info.param_names, mapping)
        self._effect_call_method(
            method_info, f"`{struct_name}.{expr.method_name}`", expr.line)
        # DF-216h: the resolved winner's extension aliases (the pre-resolution
        # map above is keyed by the struct's declared names alone).
        if receiver_args:
            self._receiver_type_subst(struct_info, receiver_args, method_info,
                                      type_map)
        # Fold the static method's OWN generic type params (design 105) into the
        # substitution alongside the struct's args.
        if method_info.type_params:
            for tp, ta in zip(method_info.type_params, expr.type_args or []):
                type_map[tp.name] = self._resolve_type(ta)
            self._check_type_param_bounds(
                method_info.type_params, type_map, expr.line, expr.column)
        param_types = method_info.param_types  # static: no self slot
        if type_map:
            param_types = [t.substitute(type_map) if t is not None else t
                           for t in param_types]
        self._finish_overloaded_args(expr, param_types, arg_types, mapping)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping if self._call_has_labels(expr) else None,
            param_types, method_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments], aligned_types,
                                     param_names=aligned_names)
        ret = method_info.return_type
        if ret is not None and type_map:
            ret = ret.substitute(type_map)
        return ret

    def _check_module_function_call(self, expr: MethodCall, func_info) -> Optional[SawType]:
        """Check a module function call: ModuleName.function(args)"""
        # DF-158d: `task.yield_now()` is the COOPERATIVE-YIELD INTRINSIC, not a
        # call to a function that happens to contain one.
        #
        # Design 114 made `yield_now` a stdlib-internal intrinsic with a public
        # std.task WRAPPER, and said the wrapper is transparent: a user call
        # lowers to the intrinsic itself, with no extra frame. That holds for
        # every spelling that puts the name in scope BARE (`import std.task.*`,
        # `import std.task.{yield_now}`), which land in the intrinsic branch of
        # `_check_function_call`. Design 150's QUALIFIER spelling arrived later
        # and did not: it resolved to the wrapper as an ordinary cross-module
        # free function, which the coroutine transform cannot embed, so the
        # caller got no state split, the yield ran outside a frame, and the task
        # never ceded — a silent no-op of the one escape hatch a pure-compute
        # loop has. Route it to the intrinsic here and mark the node so the
        # transform can lower it as one.
        if (expr.method_name == "yield_now"
                and getattr(func_info, 'def_module', ()) == ("<std>", "task")):
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`yield_now` takes no arguments, but "
                    f"{len(expr.arguments)} were given", expr.line, expr.column)
            expr.is_yield_intrinsic = True
            self._effect_direct_source("yield_now", expr.line)
            return SawType(TypeKind.VOID)
        # Design 249: name the exact definition. A cross-module free function
        # used to be reachable by its plain name because no other module could
        # hold one, so this path never stamped a symbol; a name two modules
        # declare now carries a `$M$` module tag, and the qualified spelling is
        # precisely the one that says which module is meant.
        if getattr(func_info, 'mangled_name', ""):
            expr.resolved_symbol = func_info.mangled_name
        # design 24 item 3: record the suspend-graph edge for a module-qualified
        # call. In the whole-program (single-file) path the callee's node is
        # registered under its name and the edge connects; a cross-module callee
        # into a separately-checked module resolves to no node and is a
        # non-suspending leaf (design 22 §5), which is safe today.
        self._effect_call_function(func_info, expr.method_name, expr.line)
        # DF-238a: THREAD THE RESOLVED CALLEE'S SIGNATURE, exactly as the bare
        # spelling of this same call does. This path resolved the callee and
        # then checked the arguments against its RAW declared types — so the
        # expected type never reached the argument, and every consequence of
        # that followed: a bare literal stayed at platform `Int` and was
        # silently truncated into a fixed-width parameter (or, on a 32-bit
        # target, fell out of the fold domain as an ICE), generic type
        # arguments were never solved, and a defaulted parameter could not be
        # omitted because the arity test compared against the full list.
        # The two qualified MEMBER paths beside this one (a static method, a
        # constructor) were always correct, which is where the shape below
        # comes from.
        param_types = list(func_info.param_types)
        return_type = func_info.return_type
        if func_info.type_params:
            # design 93 + 105: infer omitted type arguments from the arguments
            # (a partial explicit prefix pins its parameters, the rest infer).
            if len(expr.type_args or []) < len(func_info.type_params):
                infer_mapping = self._infer_label_mapping(
                    expr, list(func_info.param_names), func_info.default_values)
                full = self._solve_call_type_args(
                    func_info.type_params, func_info.param_types, expr,
                    infer_mapping, {}, expr.type_args,
                    f"function `{expr.method_name}`", expr.line, expr.column,
                    default_values=func_info.default_values)
                if full is None:
                    return None
                expr.type_args = [full[tp.name] for tp in func_info.type_params]
            if len(expr.type_args) != len(func_info.type_params):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{expr.method_name}` expects "
                    f"{len(func_info.type_params)} type argument(s), "
                    f"but {len(expr.type_args)} were given",
                    expr.line, expr.column
                )
                return None
            type_map: Dict[str, SawType] = {}
            for tp, ta in zip(func_info.type_params, expr.type_args):
                type_map[tp.name] = self._resolve_type(ta)
            # design 105 + 219 wave C: inferred (or explicit) type args are
            # bound-checked, and the callee's inferred tier requirement is
            # discharged, at the shared entry point.
            self._check_type_param_bounds(
                func_info.type_params, type_map, expr.line, expr.column,
                callee_decl=func_info.ast_node,
                display=f"`{expr.method_name}`")
            # design 70 (A5): the deferred poly-call edge, as the bare path
            # records it, so a suspending instantiation taints this caller.
            resolved_args = [type_map.get(tp.name)
                             for tp in func_info.type_params]
            if all(a is not None and self._is_concrete_type(a)
                   for a in resolved_args):
                self._effect_record_poly_call(
                    expr.method_name, resolved_args, f"`{expr.method_name}`",
                    expr.line)
            param_types = [t.substitute(type_map) if t is not None else t
                           for t in param_types]
            if return_type is not None:
                return_type = return_type.substitute(type_map)
        elif expr.type_args:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"function `{expr.method_name}` is not generic but was called "
                f"with type arguments",
                expr.line, expr.column
            )
        # Default parameter values (design 53): an omitted trailing argument is
        # filled at the call site, so a call may provide between `required` and
        # all of the parameters.
        dvals = func_info.default_values or []
        has_defaults = any(dv is not None for dv in dvals)
        required = (sum(1 for dv in dvals if dv is None) if has_defaults
                    else len(param_types))
        # Design 66: labeled arguments bind by the binding rule; positional-only
        # calls keep the exact legacy arity check and identity binding.
        has_labels = self._call_has_labels(expr)
        if has_labels:
            mapping = self._bind_args(expr, list(func_info.param_names),
                                      func_info.default_values, expr.method_name)
            if mapping is None:
                return return_type
        else:
            mapping = None
            if (len(expr.arguments) < required
                    or len(expr.arguments) > len(param_types)):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    (f"function `{expr.method_name}` takes between {required} "
                     f"and {len(param_types)} argument(s), but "
                     f"{len(expr.arguments)} were given") if has_defaults else
                    (f"function `{expr.method_name}` takes {len(param_types)} "
                     f"argument(s), but {len(expr.arguments)} were given"),
                    expr.line, expr.column
                )
                return return_type
        # Design 108: an omitted default on a GENERIC callee is checked against
        # its INSTANTIATED parameter type, per call.
        if func_info.type_params:
            self._check_generic_call_defaults(expr, func_info, param_types,
                                              mapping)
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] if mapping is not None else i
            expected_type = param_types[p] if p < len(param_types) else None
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type,
                                               as_call_argument=True)
            else:
                # Design 87/205: the literal adopts the parameter's fixed width
                # and is range-checked AT THE LITERAL — the whole point of
                # threading the signature here.
                self._apply_literal_expected_type(arg.value, expected_type)
                arg_type = self._check_expression(arg.value)
            declared = (func_info.param_types[p]
                        if p < len(func_info.param_types) else None)
            allow_wrap = self._df3_allow_wrap(
                declared, {tp.name for tp in (func_info.type_params or [])})
            if self._try_existential_arg_coercion(arg, arg_type, expected_type):
                pass  # `&concrete -> &any Trait` erasure (or its error) handled
            elif arg_type and expected_type is not None and not self._arg_type_ok(arg.value, arg_type, expected_type, allow_wrap):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{func_info.param_names[p]}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column,
                    hint=self._int_conversion_hint(arg_type, expected_type)
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping, param_types, func_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments],
                                     aligned_types, param_names=aligned_names)
        return return_type

    def _check_module_struct_init(self, expr: MethodCall, struct_sym) -> Optional[SawType]:
        """Check a module-qualified struct initialization: ModuleName.StructName(args)

        Uses the struct symbol directly instead of looking up by name.
        """
        struct_name = expr.method_name
        # Design 144: `mod.Point(...)` resolved through the module's namespace,
        # so the identity is known HERE. Stamp it for codegen and build every
        # returned type from it — the bare `Point` would be re-resolved against
        # the merged namespace, which is exactly what this design removes.
        identity = getattr(struct_sym, 'type_identity', "") or struct_name
        expr.resolved_type_identity = identity
        # Build field inits from arguments
        field_inits = [(arg.name, arg.value) for arg in expr.arguments if arg.name]
        if all(arg.name is None for arg in expr.arguments):
            # Positional arguments - use symbol's field_order
            field_inits = []
            for arg, field_name in zip(expr.arguments, struct_sym.field_order):
                field_inits.append((field_name, arg.value))

        provided_params = {field_name for field_name, _ in field_inits}
        field_names = set(struct_sym.fields.keys())
        matches_fields = provided_params == field_names

        # Check for matching init methods
        matching_inits = []
        for method_name, method_info in struct_sym.methods.items():
            if method_info.is_init:
                init_param_names = set(method_info.param_names)
                if provided_params == init_param_names:
                    matching_inits.append(method_info)
        # Also check init_methods list
        for method_info in struct_sym.init_methods:
            init_param_names = set(method_info.param_names)
            if provided_params == init_param_names:
                matching_inits.append(method_info)

        total_matches = (1 if matches_fields else 0) + len(matching_inits)
        if total_matches == 0:
            available_inits = [m.param_names for m in struct_sym.methods.values() if m.is_init]
            available_inits.extend([m.param_names for m in struct_sym.init_methods])
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"no matching initializer for `{struct_name}` with parameters: {', '.join(sorted(provided_params))}",
                expr.line, expr.column,
                hint=f"field init expects: {', '.join(sorted(field_names))}" +
                     (f"; available init methods: {available_inits}" if available_inits else "")
            )
            return SawType(TypeKind.STRUCT, struct_name=identity, symbol=struct_sym)
        elif total_matches > 1:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"ambiguous initializer for `{struct_name}` - matches both field initialization and custom init",
                expr.line, expr.column,
                hint="use different parameter names in init method to disambiguate"
            )
            return SawType(TypeKind.STRUCT, struct_name=identity, symbol=struct_sym)

        if matches_fields:
            # Member visibility (design 80): cross-module memberwise construction
            # of a module-qualified struct requires all fields visible.
            for _fname in struct_sym.field_order:
                self._check_field_visible(struct_sym, _fname, struct_name, expr)
            # Field initialization
            # design 27 item 3: record "field init, no custom init" so codegen
            # builds the struct memberwise rather than dispatching to an init.
            expr.resolved_init_params = None
            for field_name, field_value in field_inits:
                expected_type = struct_sym.fields[field_name]
                actual_type = self._check_init_field_value(field_value, expected_type)
                if actual_type and not self._arg_type_ok(field_value, actual_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"field `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column,
                        hint=self._int_conversion_hint(actual_type, expected_type)
                    )
                self._check_value_transfer(field_value, expected_type, "struct field",
                                           field_value.line, field_value.column)
        else:
            # Custom init method
            method_info = matching_inits[0]
            # Member visibility (design 80): gate a module-qualified custom init.
            self._check_method_visible(struct_name, "init", method_info, expr)
            # design 27 item 3: record which init matched so codegen dispatches to
            # the custom initializer (the module path previously left this unset,
            # so a module-qualified custom init silently fell through to a zeroed
            # memberwise build).
            expr.resolved_init_params = method_info.param_names
            # design 24 item 3: record the suspend-graph edge to the custom init.
            self._effect_call_method(
                method_info, f"`{struct_name}.init`", expr.line)
            init_values = []
            init_param_types = []
            for field_name, field_value in field_inits:
                param_idx = method_info.param_names.index(field_name)
                expected_type = method_info.param_types[param_idx]
                actual_type = self._check_init_field_value(field_value, expected_type)
                if actual_type and not self._arg_type_ok(field_value, actual_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"argument `{field_name}` expects `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )
                self._check_value_transfer(field_value, expected_type, "init argument",
                                           field_value.line, field_value.column)
                init_values.append(field_value)
                init_param_types.append(expected_type)
            self._check_call_exclusivity(init_values, init_param_types)

        return self._init_call_type(
            matching_inits[0] if not matches_fields else None,
            SawType(TypeKind.STRUCT, struct_name=identity, symbol=struct_sym))

    def _check_static_method_call(self, expr: MethodCall, struct_name: str,
                                   struct_info, method_info) -> Optional[SawType]:
        """Check a static method call: StructName.method(args)"""
        # Design 144: the receiver type's identity is what its method symbols
        # are mangled against, so codegen must dispatch on it rather than on
        # the name written at the call site.
        expr.resolved_type_identity = self._sym_identity(struct_info, struct_name)
        # DF-184a: record that this is a static call and which type owns the
        # method. A static call carries no receiver expression, so the coroutine
        # transform has nothing to read a struct name off — without this stamp a
        # suspending static method is never embedded as a sub-frame.
        expr.is_static_method_call = True
        expr.static_receiver = struct_name
        # Member visibility (design 80): gate the static method cross-module.
        self._check_method_visible(struct_name, expr.method_name, method_info, expr)
        # design 24 item 3: record the suspend-graph edge to the static method.
        self._effect_call_method(
            method_info, f"`{struct_name}.{expr.method_name}`", expr.line)
        required_count = sum(1 for dv in method_info.default_values if dv is None)
        # Design 66: labeled arguments bind by the binding rule; positional-only
        # calls keep the exact legacy arity checks and identity binding.
        has_labels = self._call_has_labels(expr)
        if has_labels:
            mapping = self._bind_args(expr, list(method_info.param_names),
                                      method_info.default_values,
                                      f"{struct_name}.{expr.method_name}")
            if mapping is None:
                return method_info.return_type
        else:
            mapping = None
            if len(expr.arguments) < required_count:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"static method `{struct_name}.{expr.method_name}` takes at least {required_count} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return method_info.return_type
            if len(expr.arguments) > len(method_info.param_types):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"static method `{struct_name}.{expr.method_name}` takes at most {len(method_info.param_types)} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return method_info.return_type
        # Build the struct type-param -> concrete-arg map from the receiver's
        # explicit type args (default-filled, design 37), so a static factory
        # whose PARAMETERS mention the struct's type params — `Box<Int>.make(v: T)`
        # — checks `v` against the concrete `Int`, not the abstract `T`. Vector's
        # `try_with_capacity(n: Int)` has no such param and is unaffected.
        obj_type_args = getattr(expr.object, 'type_args', None)
        struct_type_params = getattr(struct_info, 'type_params', None)
        type_map = {}
        if obj_type_args and struct_type_params:
            resolved_args = [self._resolve_type(ta) for ta in obj_type_args]
            resolved_args = self._append_default_type_args(struct_name, resolved_args)
            self._receiver_type_subst(struct_info, resolved_args, method_info,
                                      type_map)
        # DF-216c: fold the STATIC's own generic type params in on top — a
        # static has no `self` slot, so the logical parameter list starts at 0.
        # Without this the method's `U` reached the argument check below
        # unsubstituted, and neither `Plain.probe(99i64)` nor the explicit
        # `Plain.probe<Int64>(99i64)` could ever type-check.
        if not self._fold_method_type_args(expr, method_info, type_map, 0):
            return method_info.return_type
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] if mapping is not None else i
            declared_type = method_info.param_types[p]
            expected_type = declared_type
            if expected_type is not None and type_map:
                expected_type = expected_type.substitute(type_map)
            if not isinstance(arg.value, ClosureExpr):
                self._apply_literal_expected_type(arg.value, expected_type)
            arg_type = self._check_expression(arg.value)
            allow_wrap = self._df3_allow_wrap(
                declared_type, set(type_map.keys()) if type_map else None)
            if self._try_existential_arg_coercion(arg, arg_type, expected_type):
                pass  # `&concrete -> &any Trait` erasure (or its error) handled
            elif arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type, allow_wrap):
                param_name = method_info.param_names[p]
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column,
                    hint=self._int_conversion_hint(arg_type, expected_type)
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping, method_info.param_types, method_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments],
                                     aligned_types,
                                     param_names=aligned_names)
        # For a static factory on a GENERIC struct called with explicit type
        # args (`Vector<Int>.try_with_capacity(...)`), substitute the struct's
        # type params into the return type so the caller sees the concrete
        # instantiation (`Result<Vector<Int>, AllocError>`). Without this the
        # return type keeps the generic `T`, and a `match` on the result can't
        # resolve its monomorphized enum. Positional map: the struct's type
        # params line up with the type args on the call's object.
        # Substitute the same map into the return type so the caller sees the
        # concrete instantiation (`Result<Vector<Int, Global>, AllocError>`,
        # `Box<Int, Global>`) rather than the abstract `T`/`A` — needed so a
        # `match` resolves its monomorphized enum and the extracted value finds
        # its methods (design 37 default-fill already applied when building the map).
        ret = method_info.return_type
        if ret is not None and type_map:
            ret = ret.substitute(type_map)
        return ret

    def _check_self_expr(self, expr: SelfExpr) -> Optional[SawType]:
        """Check 'self' keyword usage."""
        if self.current_method is None:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                "'self' can only be used inside methods",
                expr.line, expr.column
            )
            return None
        var_info = self.current_scope.lookup("self")
        if not var_info:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                "'self' not found in method scope",
                expr.line, expr.column
            )
            return None
        return var_info.type

    def _check_enum_init(self, expr: EnumInit) -> Optional[SawType]:
        """Check enum variant initialization."""
        # Use direct symbol if available (for module-qualified enums)
        enum_info = expr.enum_symbol if expr.enum_symbol else self.get_enum_info(expr.enum_name)
        if enum_info is None:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined enum `{expr.enum_name}`",
                expr.line, expr.column
            )
            return None
        # Design 144: an enum reference carries its identity onward, exactly
        # like a struct one — a backed enum's `as` and `from(raw:)` both key on
        # it, so a private `enum Header` in two modules stays two enums with
        # two tag tables.
        expr.enum_name = (getattr(enum_info, 'type_identity', "")
                          or expr.enum_name)
        type_mapping: Dict[str, SawType] = {}
        if enum_info.type_params:
            if not expr.type_args:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"generic enum `{expr.enum_name}` requires type arguments",
                    expr.line, expr.column,
                    hint=f"use `{expr.enum_name}<...>.{expr.variant_name}(...)`"
                )
            elif len(expr.type_args) != len(enum_info.type_params):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"expected {len(enum_info.type_params)} type argument(s), got {len(expr.type_args)}",
                    expr.line, expr.column
                )
            else:
                for type_param, type_arg in zip(enum_info.type_params, expr.type_args):
                    type_mapping[type_param.name] = type_arg
        if expr.variant_name not in enum_info.variants:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"enum `{expr.enum_name}` has no variant `{expr.variant_name}`",
                expr.line, expr.column
            )
            return None
        expected_params = self._variant_payload_types(
            enum_info, expr.variant_name, type_mapping)
        if len(expr.arguments) != len(expected_params):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"variant `{expr.variant_name}` expects {len(expected_params)} arguments, got {len(expr.arguments)}",
                expr.line, expr.column
            )
            return None
        expected_dict = {name: typ for name, typ in expected_params}
        expected_list = expected_params
        for i, arg in enumerate(expr.arguments):
            if arg.is_named:
                if arg.name not in expected_dict:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"variant `{expr.variant_name}` has no parameter named `{arg.name}`",
                        expr.line, expr.column
                    )
                    continue
                expected_type = expected_dict[arg.name]
                # Design 87: adopt a fixed-width payload type + range check.
                # This ran POST-HOC — after the argument was checked and after
                # the compatibility test below — so the test saw a bare literal
                # at platform width and the (now closed) platform-pair
                # permission was what let it through. Stamped BEFORE the check,
                # like every other argument path (design 205).
                self._apply_literal_expected_type(arg.value, expected_type)
                arg_type = self._check_expression(arg.value)
                if arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected type `{expected_type}` for parameter `{arg.name}`, got `{arg_type}`",
                        arg.value.line, arg.value.column,
                        hint=self._int_conversion_hint(arg_type, expected_type)
                    )
                self._check_value_transfer(arg.value, expected_type, "enum payload",
                                           arg.value.line, arg.value.column)
            else:
                if i >= len(expected_list):
                    continue
                param_name, expected_type = expected_list[i]
                # Design 87 / design 205: stamped BEFORE the check, as above.
                self._apply_literal_expected_type(arg.value, expected_type)
                arg_type = self._check_expression(arg.value)
                if arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected type `{expected_type}` for parameter `{param_name}`, got `{arg_type}`",
                        arg.value.line, arg.value.column,
                        hint=self._int_conversion_hint(arg_type, expected_type)
                    )
                self._check_value_transfer(arg.value, expected_type, "enum payload",
                                           arg.value.line, arg.value.column)
        return SawType(TypeKind.ENUM, enum_name=expr.enum_name, type_args=expr.type_args, symbol=enum_info)

    def _check_match_expr(self, expr: MatchExpr) -> Optional[SawType]:
        """Check match expression."""
        from .core import VariableInfo, Scope
        self._check_duplicate_match_arms(expr)
        matched_type = self._check_expression(expr.matched_expr)
        if matched_type is None:
            return None
        # Normalize a STRUCT-kind user enum (or Result) to its ENUM form. A
        # generic function's declared return type (e.g. `Result<T, E>`) is stored
        # unresolved, so a call like `wrapOk<Int, Int>(7)` yields a STRUCT-kind
        # `Result<Int, Int>`; the concrete-consumer path resolves it at binding
        # time, but a direct `match` at the call site must resolve it here too
        # (brief 36, L7).
        matched_type = self._resolve_type(matched_type)
        # design 63 T1d: route value/tuple scrutinees, and any match using guards
        # or literal/range/tuple patterns, through the general pattern checker.
        # Classic enum-variant/wildcard matches keep the switch path untouched.
        if self._match_needs_general(expr, matched_type):
            return self._check_match_general(expr, matched_type)
        if matched_type.kind != TypeKind.ENUM or matched_type.enum_name is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"match expression requires an enum type, got `{matched_type}`",
                expr.line, expr.column
            )
            return None

        # Store the matched type for codegen (avoids needing to match by LLVM type)
        expr.matched_enum_type = matched_type

        enum_info = self.get_enum_info(matched_type.enum_name, from_type=matched_type)
        if enum_info is None:
            return None
        type_mapping: Dict[str, SawType] = {}
        if enum_info.type_params and matched_type.type_args:
            for type_param, type_arg in zip(enum_info.type_params, matched_type.type_args):
                type_mapping[type_param.name] = type_arg
        # DF-190a (design 193 u1, pulled forward): a match on an OWNED enum
        # scrutinee CONSUMES it — codegen hands the payload to the arm bindings
        # and suppresses the scrutinee's own drop (codegen/match.py, design 61
        # L14/L15) — but nothing here recorded that transfer, so a second
        # `match s` compiled silently and the payload deinit'd TWICE. Mirror
        # codegen's consume gate and mark the binding moved: a plain local
        # binding (matching through a `&T`/`&var T` binding stays a borrow; a
        # temporary has no binding to mark), an enum whose tier is an OWNING
        # one, carrying at least one payload the drop glue would touch. An
        # Copy-tier enum is NOT marked — its reads are retain-copies
        # by policy, and codegen agrees since design 193 unit 1: it BORROWS such
        # a scrutinee and retains each arm binding (DF-190d). Both gates ask the
        # one oracle, `Namespace.read_policy` over the copy tier.
        if isinstance(expr.matched_expr, Identifier):
            scrut_info = self.current_scope.lookup(expr.matched_expr.name)
            if (scrut_info is not None
                    and scrut_info.type.kind != TypeKind.REFERENCE
                    and self.namespace.read_policy(matched_type) in ('nocopy', 'explicit')):
                has_owning_payload = False
                for _vname in enum_info.variants:
                    for _, ftype in self._variant_payload_types(
                            enum_info, _vname, type_mapping):
                        if self.namespace.copy_tier(ftype) != 'free':
                            has_owning_payload = True
                            break
                    if has_owning_payload:
                        break
                if has_owning_payload:
                    self._mark_binding_moved(scrut_info, expr.matched_expr.name,
                                             expr.line, expr.column)
        arm_types = []
        matched_variants = set()
        has_wildcard = False
        # Move dataflow (design 15 rule 6): every arm is a branch from the same
        # entry state; after the (exhaustive) match a binding is may-moved if any
        # non-diverging arm moved it.
        entry_moves = self._snapshot_moves()
        arm_move_states = []
        for arm in expr.arms:
            if arm.variant_name == "_":
                has_wildcard = True
                if arm.bindings:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "wildcard pattern `_` cannot have bindings",
                        arm.line, arm.column
                    )
                self.moved_bindings = dict(entry_moves)
                if isinstance(arm.body, Block):
                    arm_type = self._check_block(arm.body)
                else:
                    arm_type = self._check_expression(arm.body)
                arm_move_states.append((self._snapshot_moves(), self._arm_diverges(arm.body)))
                arm_types.append(arm_type)
                continue
            if arm.variant_name not in enum_info.variants:
                self._error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"enum `{matched_type.enum_name}` has no variant `{arm.variant_name}`",
                    arm.line, arm.column
                )
                continue
            matched_variants.add(arm.variant_name)
            variant_params = self._variant_payload_types(
                enum_info, arm.variant_name, type_mapping)
            if len(arm.bindings) != len(variant_params):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"variant `{arm.variant_name}` has {len(variant_params)} associated values, got {len(arm.bindings)} bindings",
                    arm.line, arm.column
                )
                continue
            old_scope = self.current_scope
            self.current_scope = Scope(parent=old_scope)
            self.moved_bindings = dict(entry_moves)
            for binding_name, (_, param_type) in zip(arm.bindings, variant_params):
                # Skip wildcard bindings - they don't create variables
                if binding_name == '_':
                    continue
                # Design 100: a variant-pattern binding BINDS (it does not
                # compare) — shadowing an enclosing binding is a flat error.
                self._check_shadowing(binding_name, None, arm.line, arm.column,
                                      site="pattern")
                # design 130 rule 3, intake (design 193 unit 7) — the enum-switch
                # twin of the `_check_pattern` line: binding an unsafe payload is
                # contact even when the arm never reads it.
                self._note_unsafe_contact(
                    param_type, arm, "its body binds a value of unsafe type")
                var_info = VariableInfo(
                    type=param_type,
                    mutable=False,
                    line=arm.line,
                    column=arm.column
                )
                if not self.current_scope.define(binding_name, var_info):
                    self._error(
                        ErrorKind.DUPLICATE_VARIABLE,
                        f"binding `{binding_name}` is already defined in this scope",
                        arm.line, arm.column
                    )
            if isinstance(arm.body, Block):
                arm_type = self._check_block(arm.body)
            else:
                arm_type = self._check_expression(arm.body)
            arm_move_states.append((self._snapshot_moves(), self._arm_diverges(arm.body)))
            arm_types.append(arm_type)
            self.current_scope = old_scope
        # Merge arm move-states (excluding diverging arms). If no arm produced a
        # state (all were error arms), fall back to the entry state.
        if arm_move_states:
            self.moved_bindings = self._merge_move_branches(entry_moves, arm_move_states)
        else:
            self.moved_bindings = dict(entry_moves)
        if not has_wildcard:
            all_variants = set(enum_info.variants.keys())
            missing_variants = all_variants - matched_variants
            if missing_variants:
                missing_list = ", ".join(f"`{v}`" for v in sorted(missing_variants))
                self._error(
                    ErrorKind.NON_EXHAUSTIVE_MATCH,
                    f"match is not exhaustive, missing variants: {missing_list}",
                    expr.line, expr.column,
                    hint="add missing cases or use `case _ ->` as a default"
                )
        return self._reconcile_match_arm_types(expr, arm_types)

    @staticmethod
    def _arm_yields_no_value(arm_type: Optional[SawType]) -> bool:
        """True when a match arm contributes NO value to the match's result.

        Divergence reaches this function under TWO spellings, and DF-140e was
        conflating them:

        * an arm typed NEVER — a `panic(...)` expression arm (design 49);
        * an arm whose BLOCK has no final expression because every path already
          left the function (`case Ok(v) -> { ...; return }`), which
          `_check_block` reports as a plain `None`.

        Both terminate their basic block, so neither reaches the phi at the
        match's merge. Treating the second as "the arm's type", rather than as
        "no value", made the whole match type NEVER whenever such an arm came
        first — and a NEVER body is compatible with every return type, so the
        Result/Err (or Optional) auto-wrap was skipped and the surviving arm's
        value was returned RAW. `_reconcile_optional_arms` already used this
        convention; the loops below now agree with it.
        """
        return arm_type is None or arm_type.kind == TypeKind.NEVER

    def _reconcile_match_arm_types(self, expr: MatchExpr, arm_types) -> Optional[SawType]:
        """Compute a match expression's result type from its arm types, honoring
        NEVER arms (design 49) and Result auto-wrap. Shared by the enum-switch
        path and the general pattern path (design 63)."""
        if not arm_types:
            return None
        # design 49 + DF-140e: an arm that yields no value (a diverging
        # `panic(...)`, or a block whose every path returned) contributes
        # nothing to the match's type — skip such arms when computing the common
        # arm type. If NO arm yields a value, the whole match is NEVER.
        result_type = None
        for at in arm_types:
            if self._arm_yields_no_value(at):
                continue
            result_type = at
            break
        if result_type is None:
            return SawType(TypeKind.NEVER)

        # DF10: arms mixing an optional (`T?` / `None`) with a bare `T` must ALL
        # become `T?`. Left alone the compatibility loop below either reconciles
        # to the bare `T` (so codegen mixes a bare `ptr` from the value arm with a
        # `{i1, ptr}` from the `None` arm in one phi -> LLVM verifier error) or
        # errors outright. Detect the optional target, then wrap each bare,
        # non-None arm in `OptionalWrap` so the match yields a homogeneous `T?`
        # value — the exact mirror of the Result auto-wrap below.
        opt_reconciled = self._reconcile_optional_arms(expr, arm_types)
        if opt_reconciled is not None:
            return opt_reconciled

        for arm_type in arm_types:
            if self._arm_yields_no_value(arm_type):
                continue
            # design 205: an INTEGER pair is design 195 rule 2's business — the
            # merge below owns the lossless-widening admission and the refusal.
            if (not self._both_int_kinds(result_type, arm_type)
                    and not self._types_compatible(result_type, arm_type)):
                # Check if arms could be Result auto-wrapped
                # If we're in a function returning Result<T, E> and arms return T and E,
                # they're compatible (will be auto-wrapped later).
                # design 213 entry point 3: inside a closure this is the
                # CLOSURE's return type, exactly as for the value-`if` above.
                expected_return = self._enclosing_return_type()

                if expected_return and expected_return.is_result():
                    ok_type = expected_return.type_args[0] if expected_return.type_args else None
                    err_type = expected_return.type_args[1] if expected_return.type_args and len(expected_return.type_args) > 1 else None
                    # Check if one arm is Ok type and the other is Err type
                    types_for_result = all(
                        self._arm_yields_no_value(at) or
                        (ok_type and self._types_compatible(at, ok_type)) or
                        (err_type and self._types_compatible(at, err_type))
                        for at in arm_types
                    )
                    if types_for_result:
                        # Wrap arm bodies in ResultOkWrap/ResultErrWrap
                        for i, (arm, arm_type) in enumerate(zip(expr.arms, arm_types)):
                            # An arm that yields no value — a `panic(...)`
                            # (design 49) or a block that already returned
                            # (DF-140e) — has nothing to wrap.
                            if self._arm_yields_no_value(arm_type):
                                continue
                            if ok_type and self._types_compatible(arm_type, ok_type):
                                # Wrap the arm body in ResultOkWrap
                                if isinstance(arm.body, Block) and arm.body.final_expr:
                                    arm.body.final_expr = ResultOkWrap(
                                        value=arm.body.final_expr,
                                        result_type=expected_return,
                                        line=arm.body.final_expr.line,
                                        column=arm.body.final_expr.column
                                    )
                                else:
                                    arm.body = ResultOkWrap(
                                        value=arm.body,
                                        result_type=expected_return,
                                        line=arm.body.line,
                                        column=arm.body.column
                                    )
                            elif err_type and self._types_compatible(arm_type, err_type):
                                # Wrap the arm body in ResultErrWrap
                                if isinstance(arm.body, Block) and arm.body.final_expr:
                                    arm.body.final_expr = ResultErrWrap(
                                        value=arm.body.final_expr,
                                        result_type=expected_return,
                                        line=arm.body.final_expr.line,
                                        column=arm.body.final_expr.column
                                    )
                                else:
                                    arm.body = ResultErrWrap(
                                        value=arm.body,
                                        result_type=expected_return,
                                        line=arm.body.line,
                                        column=arm.body.column
                                    )
                        return expected_return

                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"match arms have incompatible types: `{result_type}` and `{arm_type}`",
                    expr.line, expr.column
                )
                return None
        # design 195 rule 2: every arm is a TRANSFER into one merged home, so a
        # lossless widening arm is free and one that cannot widen is the ordinary
        # transfer error. Reached only once every arm passed the compatibility
        # loop above, so it reports at most one diagnostic per match.
        #
        # Codegen builds the phi at `arm_results[0]`'s type and adds every arm to
        # it. LLVM's textual `phi` gives an incoming CONSTANT no type of its own,
        # so a narrow constant arm was silently re-read at the phi's width and
        # answered correctly by accident; a narrow VARIABLE arm was an internal
        # compiler error. Widening the arms here means the phi meets one width.
        valued = [at for at in arm_types if not self._arm_yields_no_value(at)]
        merged = self._merge_value_branch_types(
            valued, "the match arms", expr.line, expr.column)
        if merged is not None and len(arm_types) == len(expr.arms):
            for arm, at in zip(expr.arms, arm_types):
                if self._arm_yields_no_value(at):
                    continue
                if isinstance(arm.body, Block):
                    arm.body.final_expr = self._widened(arm.body.final_expr, merged)
                else:
                    arm.body = self._widened(arm.body, merged)
            return merged
        return result_type

    def _reconcile_optional_arms(self, expr: MatchExpr, arm_types) -> Optional[SawType]:
        """DF10: reconcile match arms that mix `T?`/`None` with a bare `T` to a
        single `T?`, wrapping each bare non-None arm in `OptionalWrap`.

        Returns the reconciled `T?` type when the arms are such a mix (and every
        arm is the optional, a `None` literal, or the inner `T`); otherwise None,
        leaving the caller's normal reconciliation/Result-wrap path in charge.
        """
        # The optional target: an explicit `T?` arm, else `Optional<T>` inferred
        # from a `None` literal arm plus a concrete bare arm.
        inner = None
        for at in arm_types:
            if at is not None and at.kind != TypeKind.NEVER and at.is_optional():
                inner = at.inner_type
                break
        if inner is None:
            has_none = any(at is not None and at.kind != TypeKind.NEVER
                           and at.is_none_literal() for at in arm_types)
            if not has_none:
                return None
            for at in arm_types:
                if (at is not None and at.kind != TypeKind.NEVER
                        and not at.is_none_literal() and not at.is_optional()):
                    inner = at
                    break
        if inner is None:
            return None

        # Only reconcile when EVERY non-never arm is the optional, a None literal,
        # or the inner `T` — otherwise this isn't a clean optional mix; let the
        # normal path report the incompatibility.
        def _fits(at):
            return (at is None or at.kind == TypeKind.NEVER or at.is_optional()
                    or at.is_none_literal() or self._types_compatible(at, inner))
        if not all(_fits(at) for at in arm_types):
            return None

        opt_target = SawType(TypeKind.OPTIONAL, inner_type=inner)
        for arm, at in zip(expr.arms, arm_types):
            if (at is None or at.kind == TypeKind.NEVER
                    or at.is_optional() or at.is_none_literal()):
                continue
            # Wrap the bare-`T` arm body (or its block tail) into `Some(...)`.
            if isinstance(arm.body, Block) and arm.body.final_expr is not None:
                arm.body.final_expr = OptionalWrap(
                    value=arm.body.final_expr, target_type=opt_target,
                    line=arm.body.final_expr.line, column=arm.body.final_expr.column)
            else:
                arm.body = OptionalWrap(
                    value=arm.body, target_type=opt_target,
                    line=arm.body.line, column=arm.body.column)
        return opt_target

    # ===== General pattern match (design 63 T1d) =====

    _INT_PATTERN_KINDS = {
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    }

    def _check_duplicate_match_arms(self, expr: MatchExpr) -> None:
        """An EXACT duplicate arm is a compile error naming both arms (design 198).

        THE ONE PLACE this rule is judged. Arm checking has two entry points —
        `_check_match_expr` (the classic enum-variant switch) and
        `_check_match_general` (literals, ranges, tuples, guards) — and both are
        reached from `_check_match_expr`, which calls this before it picks
        between them. So the rule cannot grow a second copy that drifts, which
        is how the two spellings came to disagree in the first place: the general
        path's if-chain took the first arm silently while the switch path emitted
        a duplicate case value and died inside LLVM with no source location
        (DF-192d).

        The test is TEXTUAL pattern equality after literal normalization, never
        overlap analysis. Two arms are exempt by the ruling:

        * a GUARDED arm — a guard can fail, so a later arm with the same pattern
          is genuinely reachable (`case n if n < 0` beside `case n`);
        * a RANGE — overlapping ranges are how first-match-wins is written
          (`case 1..=9` ahead of `case 5` stays legal), and so is any pattern
          containing one.

        Everything else that repeats a pattern is dead code. Reported at the
        SECOND arm, naming the first's line.
        """
        seen: Dict[tuple, int] = {}
        for arm in expr.arms:
            if arm.guard is not None:
                continue
            if arm.pattern is not None:
                key = self._arm_pattern_key(arm.pattern)
            elif arm.variant_name == '_':
                # A SYNTHESIZED arm: the coroutine transform builds MatchExprs
                # from the legacy variant_name/bindings fields with no pattern.
                key = ('any',)
            else:
                key = ('variant', arm.variant_name,
                       tuple(('any',) for _ in arm.bindings))
            if key is None:
                continue
            first = seen.get(key)
            if first is None:
                seen[key] = arm.line
                continue
            self._error(
                ErrorKind.DUPLICATE_MATCH_ARM,
                f"duplicate match arm: {self._arm_key_description(key)} is "
                f"already matched by the arm at line {first}",
                arm.line, arm.column,
                hint="the first matching arm wins, so this one can never run — "
                     "delete it. Overlapping RANGES and GUARDED arms are not "
                     "duplicates and stay legal")

    @classmethod
    def _arm_pattern_key(cls, pattern) -> Optional[tuple]:
        """A comparable key for an arm's pattern, or None when the pattern is
        EXEMPT from the duplicate rule (design 198).

        Literal normalization means the VALUE decides, not the spelling: `case
        0x0A`, `case 10` and `case 10i8` are one pattern (an arm's literal adopts
        the scrutinee's type, so a width suffix is a spelling).

        Every irrefutable HOLE keys the same whether it is written `_` or a
        binding name, so `case Move(x, y)` and `case Move(a, b)` are one arm
        under two spellings and the second can never run. That is also the
        spelling that CRASHED: the enum lowering is a switch, and a second arm
        for one variant emitted a duplicate case value whatever it named its
        bindings.

        A RANGE returns None, and so does any pattern holding one — a range is
        the one pattern the ruling leaves to first-match-wins.
        """
        if isinstance(pattern, (WildcardPattern, BindingPattern)):
            return ('any',)
        if isinstance(pattern, LiteralPattern):
            return cls._literal_pattern_key(pattern.value)
        if isinstance(pattern, TuplePattern):
            subs = [cls._arm_pattern_key(e) for e in pattern.elements]
            if any(s is None for s in subs):
                return None
            return ('tuple', tuple(subs))
        if isinstance(pattern, EnumPattern):
            subs = [cls._arm_pattern_key(s) for s in pattern.subpatterns]
            if any(s is None for s in subs):
                return None
            return ('variant', pattern.variant_name, tuple(subs))
        # RangePattern, and anything a later brief adds that this rule has not
        # been taught to compare, is exempt rather than guessed at.
        return None

    @staticmethod
    def _literal_pattern_key(value) -> Optional[tuple]:
        """Normalize a literal pattern to `(kind, value)`, or None when it is not
        one this rule compares. `_check_pattern` accepts integer, Bool and String
        literals; a negative integer arrives as `UnaryOp('-', IntLiteral)`."""
        negated = False
        if isinstance(value, UnaryOp) and value.op == '-':
            negated = True
            value = value.operand
        if isinstance(value, IntLiteral):
            return ('int', -value.value if negated else value.value)
        if negated:
            return None
        if isinstance(value, BoolLiteral):
            return ('bool', value.value)
        if isinstance(value, StringLiteral):
            return ('string', value.value)
        return None

    @staticmethod
    def _arm_key_description(key: tuple) -> str:
        """Name a duplicate arm's pattern for its diagnostic (design 198)."""
        if key[0] == 'any':
            return "this catch-all pattern"
        if key[0] == 'int':
            return f"`{key[1]}`"
        if key[0] == 'bool':
            return "`true`" if key[1] else "`false`"
        if key[0] == 'string':
            return f'`"{key[1]}"`'
        if key[0] == 'variant':
            return f"`{key[1]}`"
        if key[0] == 'tuple':
            return "this tuple pattern"
        return "this pattern"

    def _match_needs_general(self, expr: MatchExpr, matched_type: SawType) -> bool:
        """True when a match must use the general pattern checker rather than the
        classic enum switch: a non-enum scrutinee, or an enum scrutinee whose
        arms use guards / literal / range / tuple / bare-binding patterns."""
        underlying = self._get_underlying_type(matched_type)
        if underlying.kind != TypeKind.ENUM:
            return True
        for arm in expr.arms:
            if arm.guard is not None:
                return True
            p = arm.pattern
            if p is None or isinstance(p, WildcardPattern):
                continue
            if isinstance(p, EnumPattern):
                if all(isinstance(s, (BindingPattern, WildcardPattern))
                       for s in p.subpatterns):
                    continue
                return True
            return True
        return False

    def _pattern_is_irrefutable(self, pattern) -> bool:
        """True when a pattern always matches (binds only): a wildcard, a bare
        binding, or a tuple of irrefutable elements. Used for exhaustiveness (an
        irrefutable arm is a fallback) and for `let`/`var` destructuring (only
        irrefutable patterns are allowed there)."""
        if isinstance(pattern, (WildcardPattern, BindingPattern)):
            return True
        if isinstance(pattern, TuplePattern):
            return all(self._pattern_is_irrefutable(e) for e in pattern.elements)
        return False

    def _bind_optional_pattern(self, pattern, inner_type, mutable, line, column):
        """Validate + bind an irrefutable tuple pattern against the unwrapped
        inner type of an `if let`/`guard let` over an Optional tuple (design 63)."""
        if not self._pattern_is_irrefutable(pattern):
            self._error(ErrorKind.TYPE_MISMATCH,
                        "`if let`/`guard let` tuple pattern must be irrefutable "
                        "(bindings, `_`, nested tuples)", line, column)
            return
        it = self._resolve_type_alias(inner_type) if inner_type is not None else None
        if it is None or it.kind != TypeKind.TUPLE or not it.element_types:
            self._error(ErrorKind.TYPE_MISMATCH,
                        f"tuple pattern requires an optional tuple scrutinee, got "
                        f"`{inner_type}?`", line, column)
            return
        if len(pattern.elements) != len(it.element_types):
            self._error(ErrorKind.TYPE_MISMATCH,
                        f"tuple pattern has {len(pattern.elements)} elements but the "
                        f"optional's value has {len(it.element_types)}", line, column)
            return
        self._define_irrefutable_bindings(pattern, inner_type, mutable)

    def _variant_payload_types(self, enum_info, variant_name, type_mapping=None):
        """THE read of one enum case's declared payload types (DF-267b).

        An enum case's payload types are one of the three declaration slots
        stored RAW (a struct FIELD's type and a `type` alias right-hand side are
        the other two — see `_resolve_qualified_symbol`). Raw means WRITTEN: a
        `Map<String, Int>` payload has two type arguments where the type has
        three parameters, because design 37's default fill happens at
        RESOLUTION, not at the declaration. So every position that turns a
        declared payload into a type the checker reasons with owes the same
        `_resolve_type` the struct-field twin does at `_check_member_access` —
        and the one that did not, the match arm's payload BINDING, gave the
        binding a `Map<String, Int>` whose `A` was nothing, so `fields.keys()`
        answered `Vector<String, A>` and every method on it failed its
        `A: Allocator` bound.

        Entry points, all four — every position a declared payload type is read
        out of `enum_info.variants` for its TYPE rather than for its arity:

          - the classic enum-switch `match` arm's payload bindings, and the
            owning-payload test of its consume gate (`_check_match_expr`)
          - the general pattern checker's variant table
            (`_pattern_enum_variants`), which is what serves a guarded /
            literal / range / tuple match and every nested subpattern
          - a variant CONSTRUCTION's expected argument types
            (`_check_enum_init`)
          - a `try(as Enum.Case)` routing target's payload (`_check_try_route`)

        `type_mapping` substitutes a generic enum's parameters FIRST, so a
        `case Wrap(v: T)` at `Wrap<Map<String, Int>>` resolves the argument the
        instantiation supplied rather than the abstract `T`. Answers None when
        the enum has no such variant, so a caller's own "no variant" diagnostic
        stays where it is.
        """
        params = enum_info.variants.get(variant_name)
        if params is None:
            return None
        out = []
        for pname, ptype in params:
            if type_mapping:
                ptype = ptype.substitute(type_mapping)
            out.append((pname, self._resolve_type(ptype)))
        return out

    def _pattern_enum_variants(self, expected_type: SawType):
        """Return {variant_name: [(param_name, param_type), ...]} for an enum or
        Optional scrutinee, or None if the type is not variant-matchable."""
        et = self._resolve_type(expected_type)
        if et.kind == TypeKind.OPTIONAL:
            inner = et.inner_type or SawType(TypeKind.VOID)
            return {"Some": [("value", inner)], "None": []}
        if et.kind == TypeKind.ENUM and et.enum_name is not None:
            enum_info = self.get_enum_info(et.enum_name, from_type=et)
            if enum_info is None:
                return None
            type_mapping = {}
            if enum_info.type_params and et.type_args:
                for tp, ta in zip(enum_info.type_params, et.type_args):
                    type_mapping[tp.name] = ta
            variants = {}
            for vname in enum_info.variants:
                variants[vname] = self._variant_payload_types(
                    enum_info, vname, type_mapping)
            return variants
        return None

    def _check_pattern(self, pattern, expected_type: SawType):
        """Validate a pattern against the scrutinee (sub)type and define its
        bindings in the current scope."""
        from .core import VariableInfo
        underlying = self._get_underlying_type(expected_type)
        if isinstance(pattern, WildcardPattern):
            return
        if isinstance(pattern, BindingPattern):
            # Design 100: a pattern binding BINDS (it does not compare) —
            # shadowing an enclosing binding is a flat error.
            self._check_shadowing(pattern.name, None, pattern.line,
                                  pattern.column, site="pattern")
            # design 130 rule 3, intake (design 193 unit 7): BINDING an unsafe
            # value is contact, whether or not the binding is ever read. The
            # rest of the rule runs off expression types, and a bound-and-never-
            # used pattern binding produces no expression to type — so
            # `case Filled(t) -> 1` on an unsafe payload left the function
            # undeclared with an unsafe value in scope.
            self._note_unsafe_contact(
                expected_type, pattern,
                "its body binds a value of unsafe type")
            var_info = VariableInfo(type=expected_type, mutable=False,
                                    line=pattern.line, column=pattern.column)
            if not self.current_scope.define(pattern.name, var_info):
                self._error(ErrorKind.DUPLICATE_VARIABLE,
                            f"binding `{pattern.name}` is already defined in this scope",
                            pattern.line, pattern.column)
            return
        if isinstance(pattern, LiteralPattern):
            lit_type = self._check_expression(pattern.value)
            if lit_type is not None:
                lu = self._get_underlying_type(lit_type)
                ok = False
                if lu.kind in self._INT_PATTERN_KINDS and underlying.kind in self._INT_PATTERN_KINDS:
                    ok = True
                elif lu.kind == underlying.kind and lu.kind in (TypeKind.STRING, TypeKind.BOOL):
                    ok = True
                if not ok:
                    self._error(ErrorKind.TYPE_MISMATCH,
                                f"literal pattern of type `{lit_type}` cannot match "
                                f"scrutinee of type `{expected_type}`",
                                pattern.line, pattern.column)
            return
        if isinstance(pattern, RangePattern):
            if underlying.kind not in self._INT_PATTERN_KINDS:
                self._error(ErrorKind.TYPE_MISMATCH,
                            f"range pattern requires an integer scrutinee, got `{expected_type}`",
                            pattern.line, pattern.column)
            self._check_expression(pattern.start)
            self._check_expression(pattern.end)
            return
        if isinstance(pattern, TuplePattern):
            if underlying.kind != TypeKind.TUPLE or not underlying.element_types:
                self._error(ErrorKind.TYPE_MISMATCH,
                            f"tuple pattern requires a tuple scrutinee, got `{expected_type}`",
                            pattern.line, pattern.column)
                return
            if len(pattern.elements) != len(underlying.element_types):
                self._error(ErrorKind.TYPE_MISMATCH,
                            f"tuple pattern has {len(pattern.elements)} elements but "
                            f"scrutinee has {len(underlying.element_types)}",
                            pattern.line, pattern.column)
                return
            for sub, et in zip(pattern.elements, underlying.element_types):
                self._check_pattern(sub, et)
            return
        if isinstance(pattern, EnumPattern):
            variants = self._pattern_enum_variants(expected_type)
            if variants is None:
                self._error(ErrorKind.TYPE_MISMATCH,
                            f"variant pattern `{pattern.variant_name}` requires an enum "
                            f"scrutinee, got `{expected_type}`",
                            pattern.line, pattern.column)
                return
            if pattern.variant_name not in variants:
                self._error(ErrorKind.UNDEFINED_VARIABLE,
                            f"no variant `{pattern.variant_name}` on `{expected_type}`",
                            pattern.line, pattern.column)
                return
            params = variants[pattern.variant_name]
            if len(pattern.subpatterns) != len(params):
                self._error(ErrorKind.TYPE_MISMATCH,
                            f"variant `{pattern.variant_name}` has {len(params)} "
                            f"associated values, got {len(pattern.subpatterns)}",
                            pattern.line, pattern.column)
                return
            for sub, (_pn, pt) in zip(pattern.subpatterns, params):
                self._check_pattern(sub, pt)
            return

    def _check_match_general(self, expr: MatchExpr, matched_type: SawType) -> Optional[SawType]:
        """Type check a value/tuple/guarded match (design 63 T1d)."""
        from .core import VariableInfo, Scope
        # Flag + scrutinee type for the codegen general path.
        expr.use_general_match = True
        expr.matched_scrutinee_type = matched_type
        underlying = self._get_underlying_type(matched_type)
        arm_types = []
        entry_moves = self._snapshot_moves()
        arm_move_states = []
        has_catchall = False
        bool_true = False
        bool_false = False
        covered_variants = set()  # unguarded, fully-irrefutable variant arms
        for arm in expr.arms:
            p = arm.pattern
            old_scope = self.current_scope
            self.current_scope = Scope(parent=old_scope)
            self.moved_bindings = dict(entry_moves)
            if p is not None:
                self._check_pattern(p, matched_type)
            if arm.guard is not None:
                gtype = self._check_expression(arm.guard)
                if gtype is not None and self._get_underlying_type(gtype).kind != TypeKind.BOOL:
                    self._error(ErrorKind.TYPE_MISMATCH,
                                f"match guard must be `Bool`, got `{gtype}`",
                                arm.line, arm.column)
            # Catch-all / Bool-coverage tracking (unguarded arms only — a guard
            # can fail, so a guarded arm never proves exhaustiveness).
            if arm.guard is None:
                if self._pattern_is_irrefutable(p):
                    has_catchall = True
                elif isinstance(p, LiteralPattern) and isinstance(p.value, BoolLiteral):
                    if p.value.value:
                        bool_true = True
                    else:
                        bool_false = True
                elif (isinstance(p, EnumPattern)
                      and all(self._pattern_is_irrefutable(s) for s in p.subpatterns)):
                    # A variant arm with only irrefutable payload sub-bindings
                    # fully covers that variant (enum-variant exhaustiveness on
                    # the general path — lets a guarded enum match stay exhaustive
                    # via variant coverage without a redundant `case _`).
                    covered_variants.add(p.variant_name)
            if isinstance(arm.body, Block):
                arm_type = self._check_block(arm.body)
            else:
                arm_type = self._check_expression(arm.body)
            arm_move_states.append((self._snapshot_moves(), self._arm_diverges(arm.body)))
            arm_types.append(arm_type)
            self.current_scope = old_scope
        if arm_move_states:
            self.moved_bindings = self._merge_move_branches(entry_moves, arm_move_states)
        else:
            self.moved_bindings = dict(entry_moves)
        # Exhaustiveness (design 63): literal/range/guard arms never prove it on an
        # open type — a wildcard or bare-binding arm is required. EXCEPTIONS: a
        # Bool scrutinee covered by both `true` and `false`; a closed integer
        # range-cover is NOT computed in v1 (always require a fallback).
        bool_exhausts = (underlying.kind == TypeKind.BOOL and bool_true and bool_false)
        # Enum / Optional exhaustiveness: all variants covered by unguarded,
        # fully-irrefutable variant arms.
        enum_exhausts = False
        if underlying.kind in (TypeKind.ENUM, TypeKind.OPTIONAL):
            variants = self._pattern_enum_variants(matched_type)
            if variants is not None and set(variants.keys()) <= covered_variants:
                enum_exhausts = True
        if not has_catchall and not bool_exhausts and not enum_exhausts:
            self._error(
                ErrorKind.NON_EXHAUSTIVE_MATCH,
                "match is not exhaustive: literal, range, and guarded arms do not "
                "prove exhaustiveness",
                expr.line, expr.column,
                hint="add a `case _ ->` (or a bare-binding) fallback arm",
            )
        return self._reconcile_match_arm_types(expr, arm_types)

    def _first_reference_in_type(self, t: Optional[SawType]) -> Optional[SawType]:
        """The first reference reachable from an INFERRED type (a closure's
        return), aliases resolved.

        The third entry to the one no-escape walk (`noescape.py`). It resolves
        aliases like the signature-level pass does — a closure body whose tail
        has an alias type is the same escape as one whose tail is written `&T`.
        """
        return first_reference_in(t, self._alias_target)

    def _reject_reference_closure_return(self, expr: ClosureExpr,
                                         return_type: SawType) -> SawType:
        """A closure's INFERRED return type may not name a reference (DF-163d).

        Every other return position is refused at the declaration (design 163a),
        which reads the type as WRITTEN. A closure literal writes none, so
        `{ &x }` slipped through and typed `() -> &Int` — a pointer to `x` handed
        out past the call that created it, exactly what design 163a closed for
        named functions. Recovers as the VALUE type so one mistake yields one
        message instead of a cascade.
        """
        found = self._first_reference_in_type(return_type)
        if found is None:
            return return_type
        value = found.inner_type if found.inner_type is not None else "T"
        tail = getattr(expr.body, 'final_expr', None)
        line = tail.line if tail is not None else expr.line
        column = tail.column if tail is not None else expr.column
        if found is return_type:
            names_it = "is a reference"
        else:
            names_it = f"names a reference (`{found}`)"
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"a closure may not return a reference: this body's value has type "
            f"`{return_type}`, which {names_it}, and references in Saw are "
            f"PARAMETERS ONLY — a reference borrows storage for the duration of "
            f"one call and may not escape it (designs 88/106; the Law of "
            f"Exclusivity is statically sound only because every live reference "
            f"belongs to a call still on the stack)",
            line, column,
            hint=f"yield the value instead (drop the `&`, so the closure returns "
                 f"`{value}`), or — to hand out storage something already owns — "
                 f"declare a `borrows` accessor (`... borrows -> {value}` with "
                 f"`lend`, design 141), which lends the place for a window "
                 f"rather than letting a pointer out")
        return found.inner_type if found is return_type else return_type

    def _frame_pointer_escape_error(self, expr, cap_name, cap_type,
                                    is_self_borrow) -> None:
        """THE refusal of a frame-pointer capture in an escaping closure.

        One message for every spelling that reaches the rule — the implicit
        `self` capture, the explicit `[&self]` (design 218 section 4), and a
        plain capture of a reference-typed binding — because they are one
        capture judged once. `_check_closure` names the entry points.
        """
        what = ("`self`: a method's receiver is a borrow of storage the "
                "CALLER owns" if is_self_borrow
                else f"`{cap_name}`, a reference (`{cap_type}`)")
        # Name the CONCRETE receiver type in the fixit. `Self` does not
        # resolve in a closure parameter type, so spelling the hint
        # `(&Self, ...)` would hand the author a second error.
        recv = cap_type if cap_type is not None else "Receiver"
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"an escaping closure cannot capture {what} — a reference "
            f"borrows storage for the duration of one call and may not "
            f"outlive the frame it points into",
            expr.line, expr.column,
            hint=("pass the closure straight to the call that runs it (a "
                  "non-escaping closure keeps its environment on the "
                  "stack, so borrowing the frame is sound), copy the "
                  "values it needs into locals ahead of the closure and "
                  "capture those, or take the receiver as an explicit "
                  f"closure parameter (`body: (&{recv}, Int) sync -> R`, "
                  "called as `self.run({ r, v in r.field + v })`)"
                  if is_self_borrow else
                  "pass the closure straight to the call that runs it (a "
                  "non-escaping closure keeps its environment on the "
                  "stack, so borrowing the frame is sound), or copy the "
                  "values it needs out of the referent into locals ahead "
                  "of the closure and capture those"))

    def _check_self_capture_spec(self, expr, spec, self_capture_mode,
                                 borrow_ok) -> None:
        """Check one written `[&self]` / `[&var self]` capture (design 218
        section 4).

        The spelling adds no capture KIND — it is the receiver borrow design
        216 already makes implicitly — so the only things there are to check are
        the two the written form makes expressible:

          1. that there IS a borrow receiver to capture. A free function has no
             `self` at all, and a CONSUMING `self` receiver is an owned binding
             whose ordinary value capture needs no list.
          2. that `[&var self]` is not asking a `&self` method for an exclusive
             borrow it does not hold. The reverse narrowing IS allowed —
             `[&self]` in a `&var self` method captures the receiver shared, and
             the body's writes are refused through `_self_borrow_is_exclusive`.

        The escape rule is not one of them: it is the same rule the implicit
        spelling meets, so it is reported here in the same words rather than
        through the generic borrow-capture message, which would say `&self` and
        teach nothing about receivers.
        """
        cm = getattr(self, 'current_method', None)
        if self_capture_mode is None:
            where = ("a consuming `self` receiver, which is an owned binding"
                     if cm is not None else "a function with no receiver")
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"cannot capture `self` here: this is {where}",
                spec.line, spec.column,
                hint=("`[&self]` captures a `&self` / `&var self` receiver as "
                      "a borrow; a consuming receiver is captured by value "
                      "with no capture list at all"))
            return
        if spec.mode == 'ref_var' and self_capture_mode != 'ref_var':
            name = getattr(cm, 'name', 'this method')
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`[&var self]` needs a `&var self` receiver, and `{name}` "
                f"takes `&self`: a shared borrow has no exclusive borrow to "
                f"hand out",
                spec.line, spec.column,
                hint=(f"write `[&self]` to capture the receiver as the shared "
                      f"borrow it is, or declare `{name}` with a `&var self` "
                      f"receiver"))
            return
        if not borrow_ok:
            info = self.current_scope.lookup('self')
            self._frame_pointer_escape_error(
                expr, 'self', info.type if info is not None else None, True)

    def _synthesize_place_window_captures(self, expr, outer_scope) -> None:
        """Give a PLACE WINDOW body the borrow captures it always meant (DF-169h).

        `place_uses` lowers `v[i].feed(into: &var enc)` into
        `v.[](i, { __p0 in __p0.feed(into: &var enc) })`. The closure is a
        lowering device, not a value the author wrote: the body is code from the
        ENCLOSING scope and has to run against the live bindings there. Left as
        plain captures it ran against COPIES, so a move-only local was ``cannot
        copy value of type `CborEncoder` `` anchored at a subscript that copies
        nothing, and `v[0] = w[1]` — two containers, no aliasing anywhere — was
        the ExplicitCopy twin of the same refusal.

        A window closure is always a direct argument of the accessor call, whose
        `__window` parameter is an ordinary `sync` non-escaping function type, so
        the borrow capture is legal by the same rule that admits a hand-written
        `[&var x]`. Writing SPECS rather than patching `capture_modes` after the
        fact is what makes it exactly that rule: the name is rebound in the
        closure scope, so the body's move state, its mutability and design 132's
        capture-write question are answered where `[&var x]` answers them.

        A binding that is ALREADY a reference — a `&var T` parameter forwarded
        into the window, or an ENCLOSING WINDOW's own parameter where two
        windows nest — takes its mode from the reference rather than from the
        binding's mutability, and it is not exempt: a plain capture there was
        DF-248b's silent lost write, because codegen binds a reference closure
        parameter to the POINTER with its INNER type recorded beside it, so the
        capture walk loaded the value and put a copy in the env.

        A name the body MOVES (`v.push(move h)` through a place — DF-218h) is
        spelled `[move h]`, not borrowed: `move` out of a borrow capture is not
        a transfer the language has. The window closure is non-escaping, so that
        is the DEFERRED move (ruled Aug 24) — the env carries a pointer to the
        local and the body takes the value when it runs, which is what makes
        the conditional lend's absent path leak nothing and the executed path
        free exactly once.

        ONE name is deliberately left a plain capture, and it keeps a refusal
        exactly where it was: the receiver's own ROOT (`place_window_root`).
        Borrowing it would put a second access to the root INSIDE the open
        window, which is what design 188 refuses in one call — and
        `v[0].n = v.pop()!` is exactly the invalidation that rule exists for.
        The refusal it keeps is `_place_window_root_capture_error`, whose
        teaching text is the whole of DF-248a's other half.

        `self` is never listed: design 216 already captures a receiver by
        borrow, at the mode the receiver itself carries.
        """
        if not getattr(expr, 'is_place_window', False):
            return
        if expr.capture_specs:
            return          # already synthesized (the second check re-sees them)
        from ast_nodes import CaptureSpec
        root = getattr(expr, 'place_window_root', None)
        moved = _moved_names(expr.body)
        specs = []
        for name in self._analyze_closure_captures(expr.body, outer_scope):
            if name == 'self' or name == root:
                continue
            info = outer_scope.lookup(name)
            if info is None or info.type is None:
                continue
            if info.type.kind == TypeKind.REFERENCE:
                # An ENCLOSING WINDOW's binding (nested windows in one call), or
                # a `&var T` parameter forwarded in. The borrow it already is,
                # spelled — see DF-248b for why the plain capture was not one.
                # Checked BEFORE the moved-name arm so `move` out of a reference
                # keeps its own refusal instead of becoming a bogus transfer.
                mode = 'ref_var' if info.type.reference_mutable else 'ref'
            elif name in moved:
                mode = 'move'
            else:
                mode = 'ref_var' if info.mutable else 'ref'
            specs.append(CaptureSpec(name=name, mode=mode,
                                     line=expr.line, column=expr.column))
        expr.capture_specs = specs

    def _place_window_root_capture_error(self, expr, cap_name, ctype) -> bool:
        """DF-248a: the window body names the window's OWN ROOT. Reported here,
        or False when this is not that case.

        THE ONE SITE for the refusal, matching the one exclusion in
        `_synthesize_place_window_captures` that produces it: the root stays a
        plain capture, so the copy tier answers for it, and at a refusing tier
        that answer names a container the program never copies.

        The refusal itself is design 188's and stands — borrowing the root would
        put a second access to it inside the open window, and `v[0].n = v.pop()!`
        is the invalidation the rule exists for. What is reported is the reason,
        because the shape one line up compiles: an ASSIGNMENT's right-hand side
        is defined to run before its target (design 193), so `place_uses` hoists
        a root-naming RHS out of the window and the two accesses become two
        statements. No other position has an order to hoist along — an argument
        and a body read both run after the accessor's PROLOGUE, and moving them
        ahead of it would reorder documented sequence. So the fix is the author's
        `let`, and the diagnostic says which of the two shapes they are looking
        at and why the compiler will not write that `let` for them.

        Scoped to the tiers that REFUSE. A Copy-tier root captures by value with
        no diagnostic at all today, and turning that into an error would be a new
        refusal rather than better words for an existing one.
        """
        if not getattr(expr, 'is_place_window', False):
            return False
        if ctype is None or cap_name != getattr(expr, 'place_window_root', None):
            return False
        if self.namespace.copy_tier(ctype) not in ('nocopy', 'explicit'):
            return False
        self._error(
            ErrorKind.EXCLUSIVITY_VIOLATION,
            f"cannot read `{cap_name}` from inside a place window opened on it",
            expr.line, expr.column,
            hint=(f"a window's extent is the whole expression that asks for the "
                  f"borrow, so this read sits between the accessor's prologue "
                  f"and its epilogue. Lift it above the statement and name the "
                  f"binding here — `let n = {cap_name}.len()` is the shape. An "
                  f"ASSIGNMENT is the one position that needs no rewrite: "
                  f"`{cap_name}[0].n = {cap_name}.len()` compiles, because a "
                  f"right-hand side is defined to run before its target, so the "
                  f"compiler lifts it out of the window for you. Here it "
                  f"cannot: the read would move ahead of the accessor's "
                  f"prologue, which changes the order the program runs in"))
        return True

    def _check_closure(self, expr: ClosureExpr, expected_type: Optional[SawType] = None,
                        as_call_argument: bool = False,
                        force_escape: bool = False) -> Optional[SawType]:
        """Type check a closure expression.

        `as_call_argument` is True only when the closure literal appears directly
        as an argument of the call it is passed to. A closure whose signature has
        reference parameters (`&`/`&var`) is NON-STORABLE (design 21 item 3): it
        may only appear in that position; binding/returning/capturing it is a
        conservative error until full non-escaping closures land.
        """
        from .core import VariableInfo, Scope
        # design 226, construction form 1: a `FuncPointer<F>`-EXPECTED position
        # COERCES a zero-capture literal. The body is checked against `F` like
        # any other contextually-typed closure — that is the whole of the type
        # side — and what changes is the RESULT: a `FuncPointer<F>` rather than
        # a closure value, emitted under `F`'s bare ABI. The expectation arrives
        # by parameter where the caller knows it (a call argument, a struct
        # field initializer) and by the stamp `_apply_literal_expected_type`
        # made where it does not (an annotated `let`, a `return`, a `static`).
        fp_result = self._funcpointer_expectation(expr, expected_type)
        if fp_result is not None:
            expected_type = self._funcpointer_signature(fp_result)
        outer_scope = self.current_scope
        self.current_scope = Scope(parent=outer_scope)
        # design 132 unit A: everything the body can WRITE lives at or below this
        # scope. A name that resolves past it came in by value capture, and the
        # env copy makes such a write unobservable — `_capture_write_root` reads
        # this stack to reject it (DF-122a).
        self._closure_scopes.append(self.current_scope)
        # A closure captures by value, so its body has its own function-local
        # move state (design 15); restore the enclosing state on exit.
        saved_moves = self.moved_bindings
        self.moved_bindings = {}
        # design 22: analyze the closure body as its own suspend-graph node. If
        # its target type is a `sync` function type (e.g. `Mutex.lock`'s param),
        # the closure is a sync context checked transitively suspension-free.
        self._effect_enter_closure(expr, expected_type)
        # design 130 q3: a closure that never names an unsafe type is SAFE even
        # when passed into an unsafe function — `v.with_ref(0) { e in e + 1 }`
        # sees only `&T`, and that is what keeps the reviewed wrappers usable from
        # safe code. Where an unsafe value genuinely IS handed to a closure, the
        # closure's parameter type names it. The body is checked against a fresh
        # contact slot; the verdict at the bottom of this function decides which
        # domain that contact belongs to (design 136).
        saved_unsafe_contact = self._unsafe_contact
        self._unsafe_contact = None

        # Bracketed capture list (design 16/29). Borrow captures (`&`/`&var`) are
        # legal ONLY in a closure literal passed directly to a NON-escaping
        # parameter — they lower to pointers into the enclosing frame, sound only
        # because the closure cannot outlive the call. A borrow capture defines a
        # shadowing binding in the closure scope: the name reads/writes the
        # referent, mutable iff `&var`. Value captures (`move`/`copy`/plain) are
        # handled after the body (routed through the value-transfer checkpoint).
        spec_by_name = {}
        target_escaping = bool(expected_type is not None
                               and expected_type.kind == TypeKind.FUNCTION
                               and getattr(expected_type, 'func_is_escaping', False))
        borrow_ok = as_call_argument and not force_escape and not target_escaping
        # `self`'s own borrow mode, from the enclosing method's receiver. A
        # CONSUMING `self` receiver is an owned binding and has none, which is
        # what makes it an ordinary value capture (design 216).
        cm = getattr(self, 'current_method', None)
        self_capture_mode = None
        if cm is not None and getattr(cm, 'self_is_reference', False):
            self_capture_mode = ('ref_var' if getattr(cm, 'self_mutable', False)
                                 else 'ref')
        shared_self_capture = False
        self._synthesize_place_window_captures(expr, outer_scope)
        for spec in (expr.capture_specs or []):
            if spec.name in spec_by_name:
                self._error(
                    ErrorKind.DUPLICATE_VARIABLE,
                    f"capture `{spec.name}` listed more than once",
                    spec.line, spec.column)
            spec_by_name[spec.name] = spec
            if spec.name == 'self':
                # design 218 section 4: `[&self]` / `[&var self]`, the explicit
                # spelling of the capture design 216 already makes implicitly.
                # It reaches the same frame-pointer rule (below) through the
                # same predicate; what it adds is the MODE written out loud.
                shared_self_capture = (shared_self_capture
                                       or spec.mode == 'ref')
                self._check_self_capture_spec(
                    expr, spec, self_capture_mode, borrow_ok)
                continue
            outer_info = outer_scope.lookup(spec.name)
            if outer_info is None:
                self._error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"capture of undefined variable `{spec.name}`",
                    spec.line, spec.column)
                continue
            if spec.mode in ('ref', 'ref_var'):
                if not borrow_ok:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"borrow capture `&{'var ' if spec.mode == 'ref_var' else ''}"
                        f"{spec.name}` is legal only in a closure passed directly to a "
                        f"non-escaping parameter",
                        spec.line, spec.column,
                        hint="an escaping closure outlives the frame, so it cannot "
                             "borrow it — capture by value (`move`/`copy`) instead")
                    # Fall through and bind it anyway. Recovering as the author
                    # WROTE it keeps this the only complaint about the name; the
                    # design-132 capture-write rule would otherwise fire a second
                    # time on every mutation in the body and bury the real error.
                referent = outer_info.type
                if referent is not None and referent.kind == TypeKind.REFERENCE:
                    referent = referent.inner_type
                self.current_scope.define(spec.name, VariableInfo(
                    referent, spec.mode == 'ref_var', spec.line, spec.column))

        param_types = []
        has_reference_params = False
        if expr.parameters:
            for i, param in enumerate(expr.parameters):
                expected_param = None
                if expected_type and expected_type.kind == TypeKind.FUNCTION:
                    expected_params = expected_type.param_types or []
                    if i < len(expected_params):
                        expected_param = expected_params[i]
                if getattr(param, 'is_reference', False):
                    # Reference-capture param: the bound name has the underlying
                    # type T; the closure's parameter type is `&T` / `&var T`.
                    has_reference_params = True
                    inner = None
                    if param.type_annotation:
                        inner = self._resolve_type(param.type_annotation)
                    elif expected_param is not None:
                        if expected_param.kind in (TypeKind.REFERENCE, TypeKind.POINTER):
                            inner = expected_param.inner_type
                        else:
                            inner = expected_param
                    if inner is None:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"Cannot infer type for reference parameter `{param.name}`. "
                            f"Add a type annotation: `&{'var ' if param.reference_mutable else ''}{param.name}: Type`",
                            param.line, param.column
                        )
                        inner = SawType(TypeKind.INT)
                    param_type = SawType(TypeKind.REFERENCE, inner_type=inner,
                                         reference_mutable=param.reference_mutable)
                    param_types.append(param_type)
                    # Design 100: a closure parameter shadowing an enclosing
                    # local (or module static) is a flat error.
                    self._check_shadowing(param.name, None, param.line,
                                          param.column, site="param")
                    # The name reads/writes the referent directly; mutable iff &var.
                    self.current_scope.define(param.name, VariableInfo(
                        inner, param.reference_mutable, param.line, param.column))
                    continue
                if param.type_annotation:
                    param_type = self._resolve_type(param.type_annotation)
                elif expected_param is not None:
                    param_type = expected_param
                elif expected_type and expected_type.kind == TypeKind.FUNCTION:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"Closure has more parameters than expected function type",
                        param.line, param.column
                    )
                    param_type = SawType(TypeKind.INT)
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"Cannot infer type for closure parameter `{param.name}`. Add type annotation: `{param.name}: Type`",
                        param.line, param.column
                    )
                    param_type = SawType(TypeKind.INT)
                param_types.append(param_type)
                # Design 100: a closure parameter shadowing an enclosing local
                # (or module static) is a flat error.
                self._check_shadowing(param.name, None, param.line,
                                      param.column, site="param")
                # DF-175b: a SHARED place window binds its element read-only.
                # The closure's TYPE keeps the `(&var T)` shape the accessor's
                # one lowered `__window` parameter declares — the flavor is a
                # use-site property, not a declaration one — but the BINDING is
                # a shared borrow, so a write through it is the ordinary
                # immutable-reference error rather than a write that lands in
                # storage the root holds immutably.
                bound_type = param_type
                if (getattr(param, 'place_shared_window', False)
                        and bound_type is not None
                        and bound_type.kind == TypeKind.REFERENCE
                        and bound_type.reference_mutable):
                    bound_type = SawType(TypeKind.REFERENCE,
                                         inner_type=bound_type.inner_type,
                                         reference_mutable=False)
                self.current_scope.define(param.name, VariableInfo(bound_type, False, param.line, param.column))
        elif expr.shorthand_param_count > 0:
            for i in range(expr.shorthand_param_count):
                if expected_type and expected_type.kind == TypeKind.FUNCTION:
                    expected_params = expected_type.param_types or []
                    if i < len(expected_params):
                        param_type = expected_params[i]
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"Closure uses `${i}` but expected function type only has {len(expected_params)} parameters",
                            expr.line, expr.column
                        )
                        param_type = SawType(TypeKind.INT)
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"Cannot infer type for shorthand parameter `${i}`. Use named parameters with type annotations.",
                        expr.line, expr.column
                    )
                    param_type = SawType(TypeKind.INT)
                param_types.append(param_type)
                self.current_scope.define(f"${i}", VariableInfo(param_type, False, expr.line, expr.column))
        # design 213: a closure is a CALLABLE, so the body is checked against
        # the CLOSURE's return target, not the enclosing named function's. The
        # target carries the declared return type when the call site supplied
        # one; otherwise it is None and the body's own `return`s agree among
        # themselves (see `ClosureReturnTarget`). The enclosing `try {} catch {}`
        # is cleared for the same reason — that catch sits in the OUTER frame
        # and is not on this body's error path (it ICEd in codegen: "use of
        # undefined value '%caught_error'").
        from .core import ClosureReturnTarget
        declared_ret = None
        if expected_type is not None and expected_type.kind == TypeKind.FUNCTION:
            declared_ret = expected_type.func_return_type
            if declared_ret is not None and declared_ret.kind == TypeKind.TYPE_PARAM:
                declared_ret = None      # unsolved `U` — nothing to check against
        ret_target = ClosureReturnTarget(expected=declared_ret)
        # DF-226a: a closure body's RETURN POSITIONS take the expected type the
        # same way a named function body's do — through the one funnel, BEFORE
        # the body is checked. `_check_closure` used to pin the expected return
        # onto the body for exactly two shapes (a bare-`None` tail, DF-146c, and
        # a `Never` tail, both below) and never called
        # `_apply_literal_expected_type` at all, so a closure tail was missing
        # every literal rule at once rather than one of them: a bare literal at
        # a fixed-width return stayed platform `Int` and reached codegen at the
        # wrong width (`ret i64` from an `i32` function), and an array literal
        # never learned it was a `Vector`. Routing through
        # `_stamp_return_literal_types` — the SAME chokepoint `_check_function`
        # and `_check_method` call — is what makes the two bodies one rule
        # rather than two that drift; it covers the tail expression, the arm
        # results inside it, and a top-level `return <literal>`.
        self._stamp_return_literal_types(expr.body, declared_ret)
        self._closure_returns.append(ret_target)
        saved_in_try_catch = self.in_try_catch_block
        saved_try_err_types = getattr(self, '_try_catch_error_types', None)
        # ...and `found_return_with_value` is the enclosing FUNCTION's "does the
        # body produce a value" answer. A `return 1` in a closure used to set it,
        # silently satisfying the outer function's own check.
        saved_found_return = self.found_return_with_value
        self.in_try_catch_block = False
        self._try_catch_error_types = None
        # design 218 section 4: an explicit `[&self]` narrows the receiver to a
        # SHARED borrow for this body, so every write-through-`self` rule judges
        # it as it would in a `&self` method (`_self_borrow_is_exclusive`).
        if shared_self_capture:
            self._shared_self_capture_depth += 1
        try:
            return_type = self._check_block(expr.body)
        finally:
            if shared_self_capture:
                self._shared_self_capture_depth -= 1
            self._closure_returns.pop()
            self.in_try_catch_block = saved_in_try_catch
            self._try_catch_error_types = saved_try_err_types
            self.found_return_with_value = saved_found_return
        if return_type is None:
            return_type = SawType(TypeKind.VOID)
        # A body whose every path is a `return <value>` has no tail expression,
        # so the block yields Void — but the closure plainly returns that
        # value's type. Take it from the declared type when there is one, and
        # from the returns themselves when the type is being inferred.
        # `has_return` is load-bearing: a body that returns NOTHING and ends in
        # a statement (`{ &var n in n = n + 1 }`) is genuinely Void, and reading
        # the expected type there handed `Mutex.lock<R>`'s unsolved `R` back as
        # the closure's type.
        if (ret_target.has_return
                and return_type.kind == TypeKind.VOID
                and expr.body.final_expr is None
                and not ret_target.saw_bare_return):
            if ret_target.expected is not None:
                return_type = self._resolve_type(ret_target.expected)
            elif ret_target.observed is not None:
                return_type = ret_target.observed
        # `try`s raised before the return type was known are replayed against it
        # now (design 213 entry point 4).
        for (err_type, line, column, node) in ret_target.pending_try:
            self._validate_error_propagation_against(
                return_type, err_type, line, column, node)
        # A closure may not RETURN a reference (DF-163d). Design 163a refuses a
        # written `-> &T` at every declaration that has one, and a closure
        # literal writes no return type at all — inference is the only place the
        # rule can be applied, so it is applied here. `{ &x }` is the shape:
        # it types `() -> &Int` and hands a pointer to `x` out past the call
        # that made it. The `with_ref` identity closure `{ e in e }` is NOT this
        # case — reading a reference binding yields the VALUE, so it infers `T`.
        return_type = self._reject_reference_closure_return(expr, return_type)
        # A closure passed to a known function type takes its RETURN CONTEXT from
        # that type, the same way a function body takes it from its signature —
        # so a bare `None` in tail position learns what it is a `None` OF. The
        # shape that needed it is the absent path of a conditional lend, `{ None }`
        # checked against `() sync -> T?` (design 141/146, DF-146c): without the
        # pin the optional reached codegen with no inner type at all.
        expected_ret = (expected_type.func_return_type
                        if expected_type is not None
                        and expected_type.kind == TypeKind.FUNCTION else None)
        if expected_ret is not None and expected_ret.kind == TypeKind.TYPE_PARAM:
            expected_ret = None          # unsolved `U` — nothing to pin against
        if expected_ret is not None and return_type.kind == TypeKind.NEVER:
            # A body that never comes back satisfies any expected result type,
            # and the SIGNATURE is what codegen emits — so a `{ panic(...) }`
            # closure in an `-> Int` slot must be an `-> Int` function that
            # happens never to return. This is the absent path of a conditional
            # lend reached through a force-unwrap (`v.get(i)!.m()`), where the
            # `!`'s promise becomes the panic.
            return_type = expected_ret
        elif (expected_ret is not None
                and expected_ret.kind == TypeKind.OPTIONAL
                and expected_ret.inner_type is not None):
            self._propagate_optional_type(expr.body, expected_ret)
            if (return_type.kind == TypeKind.OPTIONAL
                    and return_type.inner_type is None):
                return_type = expected_ret
            elif (not return_type.is_optional()
                    and return_type.kind not in (TypeKind.VOID, TypeKind.NEVER)
                    and expr.body.final_expr is not None):
                # A tail value where an optional is expected AUTO-WRAPS, exactly
                # as it does in a function body — `{ __p in __p }` against
                # `(&var T) sync -> T?` is the present path of a conditional
                # lend, and the wrap is what makes it a `Some` place read.
                expr.body.final_expr = OptionalWrap(
                    value=expr.body.final_expr, target_type=expected_ret,
                    line=expr.body.final_expr.line,
                    column=expr.body.final_expr.column)
                return_type = expected_ret
        elif (expected_ret is not None and expected_ret.is_result()
                and expr.body.final_expr is not None
                and self._reaches_result_autowrap(return_type, expected_ret)):
            # DF-232h — ENTRY POINT 4 of `_autowrap_into_result`. A closure's
            # TAIL takes the same Result auto-wrap a named body's tail takes.
            # Its `return` already did (that path shares the named funnel
            # through `_return_target`), so the two spellings of one intent
            # disagreed: `run({ x in 12 })` against `(Int) sync ->
            # Result<Int32, Bad>` was ``argument `f` expects ... but got `(Int)
            # -> Int32` `` while `{ x in return 12 }` compiled. The optional
            # analogue directly above is what this had no counterpart to.
            self._apply_literal_expected_type(expr.body.final_expr,
                                              expected_ret)
            outcome, wrapped = self._autowrap_into_result(
                expr.body.final_expr, return_type, expected_ret,
                "closure", expr.body.final_expr.line,
                expr.body.final_expr.column)
            if wrapped is not None:
                expr.body.final_expr = wrapped
                return_type = expected_ret
        captures = self._analyze_closure_captures(expr.body, outer_scope)
        # An explicitly-listed capture is captured even if the body scan missed
        # it (e.g. a borrow named for its side of an exclusivity check). Preserve
        # body-scan order, then append listed-but-unseen names.
        for spec in (expr.capture_specs or []):
            if spec.name not in captures and outer_scope.lookup(spec.name):
                captures.append(spec.name)
        expr.captures = captures
        expr.has_reference_params = has_reference_params
        # `self` is a BORROW capture, never a value one (design 216, DF-216a).
        # A method's receiver IS a reference binding — `&self` names the callee's
        # own copy of it, `&var self` names the caller's storage — so a closure
        # naming `self` must capture the POINTER, exactly as it captures a
        # `&T`/`&var T` parameter: the body then reads (and, through `&var self`,
        # writes) the live receiver. A value capture would be wrong twice over —
        # it would snapshot the receiver, and it would demand of `self` a copy
        # policy no receiver ever owed. A CONSUMING `self` receiver (no `&`) is
        # an owned binding and stays a plain value capture. `self_capture_mode`
        # is computed with the capture specs, above, because design 218's
        # `[&self]` spelling is checked against it there.
        #
        # Record each capture's effective mode for codegen (design 16/29): listed
        # names take their declared mode, `self` the receiver's borrow mode, and
        # everything else is `plain`.
        expr.capture_modes = {
            name: (spec_by_name[name].mode if name in spec_by_name
                   else (self_capture_mode if (name == 'self'
                                               and self_capture_mode is not None)
                         else 'plain'))
            for name in captures
        }
        # design 226: judge the coercion's captures HERE, the moment the walk
        # has them, and recover as "captures nothing". Everything below this
        # point reacts to a capture — the frame-pointer rule, the hidden-alloc
        # gate, the value-transfer checkpoint — and each would report a second
        # diagnostic about a closure the author never meant to build.
        if fp_result is not None:
            captures = self._check_funcpointer_captures(expr, captures,
                                                        outer_scope)
        # THE FRAME-POINTER CAPTURE RULE, one predicate over its three spellings.
        # A capture that lowers to a pointer INTO the enclosing frame is sound
        # only because a non-escaping closure cannot outlive the call that runs
        # it, so it is legal only in a closure passed directly to a non-escaping
        # parameter. Three spellings reach it and all three are checked here:
        #   1. an explicit `[&x]` / `[&var x]` borrow capture — checked above at
        #      its spec, where the author wrote the `&`;
        #   2. `self` in a method, whose implicit mode is set just above;
        #   3. a REFERENCE-TYPED binding (`&T` / `&var T` parameter), whose plain
        #      capture copies the pointer itself into the env.
        # Spelling 3 used to bypass the rule entirely: an escaping closure
        # capturing a `&T` parameter compiled to `store ptr %r` into a HEAP env
        # and read the referent's frame after it died, with no diagnostic
        # (DF-216d). LANGUAGE_SPEC has always said references are parameter-only
        # and cannot escape; this is the one site that did not enforce it.
        #
        # Spelling 2 has an EXPLICIT form too since design 218 section 4
        # (`[&self]`), and it reaches this same rule — reported at its spec by
        # `_check_self_capture_spec`, which calls the same error builder, so the
        # implicit and explicit spellings are refused in identical words.
        if not borrow_ok:
            for cap_name in captures:
                if cap_name in spec_by_name:
                    continue        # already reported at its spec
                cap_info = outer_scope.lookup(cap_name)
                cap_type = cap_info.type if cap_info is not None else None
                is_self_borrow = (cap_name == 'self'
                                  and self_capture_mode is not None)
                is_ref_binding = (cap_type is not None
                                  and cap_type.kind == TypeKind.REFERENCE)
                if not (is_self_borrow or is_ref_binding):
                    continue
                self._frame_pointer_escape_error(
                    expr, cap_name, cap_type, is_self_borrow)
        # Escape analysis (design 21b E1): a closure used in value position (bound
        # to a let/var, returned, stored, or a struct field) outlives the frame
        # that built it, so its environment must be heap-allocated with captured
        # values transferred in per the transfer rules. A closure consumed
        # directly as a call argument to an ordinary function (e.g. Mutex.lock's
        # `sync` closure) does NOT escape — the callee runs it before returning,
        # so a stack env is sound and cheaper. Reference-param closures are
        # forced to be call arguments (checked below) and never escape. `spawn`
        # is the exception: it is a call argument yet the task outlives the call,
        # so the spawn handler passes force_escape=True.
        expr.escapes = force_escape or (
            (not as_call_argument) and (not has_reference_params))
        # design 135: an escaping closure with captures heap-allocates its
        # refcounted environment (design 73), and the literal says nothing about
        # it. A capture-LESS escaping closure is just a code pointer, so it stays
        # legal — the check follows codegen's own condition exactly. `spawn`'s
        # closure is excluded: it escapes only because `spawn` was written, and
        # a call that starts a task is an allocation the source named.
        if (expr.escapes and captures and not force_escape
                and self._hidden_alloc_gate()):
            self._hidden_alloc_error(
                "an escaping closure heap-allocates its captured environment",
                expr.line, expr.column,
                hint="pass the closure straight to the call that runs it (a "
                     "non-escaping closure keeps its environment on the stack), "
                     "drop the captures and take the values as parameters, or "
                     "hold the shared state in an explicit `Box`/`Arc` so the "
                     "allocation is written down")
        self.current_scope = outer_scope
        self._closure_scopes.pop()
        self.moved_bindings = saved_moves
        # Route every VALUE capture (mode plain/move/copy) through the shared
        # value-transfer checkpoint, in the OUTER scope so `move` records the
        # source binding as moved-from (design 03/15/16/29). Borrow captures
        # (ref/ref_var) are not transfers and are skipped. This makes capture
        # rules literally the call-argument rules: plain capture of a
        # NoCopy/ExplicitCopy is an error (demand `move`/`copy`); Copy is
        # retained; trivial is copied bitwise; `move`/`copy` are explicit.
        for cap_name in captures:
            mode = expr.capture_modes.get(cap_name, 'plain')
            if mode in ('ref', 'ref_var'):
                continue
            cap_info = outer_scope.lookup(cap_name)
            if cap_info is None:
                continue
            ctype = cap_info.type
            # Forwarding rule (design 16/29 item 5): a non-escaping closure value
            # (e.g. a non-escaping closure PARAMETER) may not be captured by an
            # escaping closure — its own captures could borrow a frame that dies
            # before the escaping closure runs. Genuinely-escaping function
            # values are fine.
            if (expr.escapes and ctype is not None
                    and ctype.kind == TypeKind.FUNCTION
                    and not getattr(ctype, 'func_is_escaping', False)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot capture non-escaping closure `{cap_name}` in an "
                    f"escaping closure",
                    expr.line, expr.column,
                    hint="an escaping closure outlives the frame; only call a "
                         "non-escaping closure or forward it as a non-escaping argument")
                continue
            if mode == 'move':
                mv = MoveExpr(variable=cap_name, line=expr.line, column=expr.column)
                self._check_move_expr(mv)
                continue
            if mode == 'copy':
                if self._is_no_copy_type(ctype):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"cannot `copy` capture `{cap_name}`: type `{ctype}` "
                        f"implements NoCopy",
                        expr.line, expr.column,
                        hint="use `move {}` to transfer ownership".format(cap_name))
                continue
            # The window's own ROOT, named from inside the window (DF-248a).
            # The copy tier is what refuses it today, and its noun is wrong
            # twice: the program copies no container, and the reader is looking
            # at a shape that COMPILES one line up as an assignment.
            if self._place_window_root_capture_error(expr, cap_name, ctype):
                continue
            # Plain capture: an escaping env must own its captures, so move-only
            # types are rejected; a non-escaping stack env borrows the frame, so
            # a plain capture there is also just a read — but for uniform,
            # explicit semantics we apply the same rule everywhere.
            ident = Identifier(name=cap_name, line=expr.line, column=expr.column)
            ident.resolved_type = ctype
            self._check_value_transfer(ident, ctype, "closure capture",
                                       expr.line, expr.column)
        # A closure with reference parameters is non-storable: legal only as a
        # direct call argument (design 21 item 3). Reject any other position.
        # A `FuncPointer` coercion is exempt (design 226): the rule exists
        # because a closure VALUE could outlive the frame its borrow captures
        # point into, and a coerced literal captures nothing — its reference
        # parameters are the callee's, exactly as a named `func f(x: &Int)`'s
        # are. Refusing it here would say "it cannot be bound" about a type
        # whose whole purpose is to be bound.
        if has_reference_params and not as_call_argument and fp_result is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "a closure with reference (`&`/`&var`) parameters may only be passed "
                "directly as a call argument; it cannot be bound, returned, or captured",
                expr.line, expr.column,
                hint="call the function that takes it inline, e.g. `m.lock { &var x in ... }`"
            )
        # The closure's own verdict, before the enclosing function's state is
        # restored (design 136).
        #
        # Its TYPE says `unsafe` exactly when its SIGNATURE names an unsafe type,
        # like any other function type — a closure has no effect slot to write,
        # so there is nothing else the bit could come from. That is the
        # `with_raw` shape: the callee hands an unsafe value in, and the slot it
        # was passed to already declared as much.
        #
        # Contact the BODY makes beyond that signature belongs to the ENCLOSING
        # function, which is what "a closure inherits its enclosing function's
        # unsafe domain" means in the checker. The value can only have arrived by
        # capture (the enclosing body bound it) or from a binding written inside
        # the enclosing body, so the enclosing declaration is where a reviewer
        # reads it — and the honest spelling for an unsafe closure in a safe
        # function is to declare that function `unsafe`, or to hoist the work
        # into a named one. Propagating the contact gets exactly that diagnostic
        # from `_exit_unsafe_scope`, naming the enclosing declaration.
        signature_is_unsafe = (
            any(self._type_tree_has_unsafe(pt) for pt in param_types)
            or self._type_tree_has_unsafe(return_type))
        contact = self._unsafe_contact
        self._unsafe_contact = saved_unsafe_contact
        if (contact is not None and not signature_is_unsafe
                and self._unsafe_contact is None):
            self._unsafe_contact = contact
        if fp_result is not None:
            # The coercion's verdict: the value is a `FuncPointer<F>`, not a
            # closure. `escapes` is cleared because there is nothing to escape —
            # a code address outlives every frame, which is the same fact that
            # makes the type safe.
            expr.funcpointer_target = fp_result
            expr.escapes = False
            expr.resolved_type = fp_result
            self._effect_exit()
            return fp_result
        result_type = SawType(TypeKind.FUNCTION, param_types=param_types,
                              func_return_type=return_type,
                              func_is_unsafe=signature_is_unsafe,
                              func_is_escaping=expr.escapes)
        # Record the resolved signature so codegen lowers parameter/return types
        # (including reference params) accurately rather than guessing. The
        # escaping bit rides along so codegen treats an escaping closure binding as
        # an owning value with drop glue (design 71).
        expr.resolved_type = result_type
        self._effect_exit()
        return result_type

    # ------------------------------------------------------------------ 226
    # The two construction forms of a `FuncPointer<F>`.

    def _funcpointer_expectation(self, expr, expected_type):
        """The `FuncPointer<F>` type this expression is expected to be, or None.

        Two ways one arrives, and both are read here so no position can pick up
        only one of them:
          * BY PARAMETER, where the checker already knows the slot's type — a
            call argument, a struct field initializer, a closure-typed field.
          * BY STAMP, from `_apply_literal_expected_type`, at every position
            that pushes an expected type down without threading it into the
            expression check — an annotated `let`, a `return`, a `static`
            initializer.
        """
        found = self._funcpointer_signature(expected_type)
        if found is not None:
            return expected_type
        stamped = getattr(expr, 'expected_type', None)
        if self._funcpointer_signature(stamped) is not None:
            return stamped
        return None

    def _funcpointer_decl_signature_key(self, sym):
        """A declared function's signature, keyed the way `F` is keyed."""
        return tuple(self._type_key(p) for p in (sym.param_types or [])) + (
            "->", self._type_key(sym.return_type or SawType(TypeKind.VOID)))

    def _funcpointer_target_signature_key(self, f):
        """`F`'s signature, keyed the way a declaration's is."""
        return tuple(self._type_key(p) for p in (f.param_types or [])) + (
            "->", self._type_key(f.func_return_type or SawType(TypeKind.VOID)))

    def _funcpointer_decl_is_sync(self, sym) -> bool:
        """Is this declaration a `sync` CONTEXT — checked suspension-free?

        `F` says `sync`, and the compiler may only hand out an address it can
        promise that of. Two declarations carry the promise: a `sync` effect
        slot, and `@export` (design 58 — a C-boundary root cannot suspend, and
        is checked transitively by the same machinery). A body that merely
        happens not to suspend is not one: nothing stops the next edit, and the
        error would then land on a body nobody was reading.
        """
        from ast_nodes import is_exported
        if getattr(sym, 'is_sync', False):
            return True
        decl = getattr(sym, 'decl_node', None) or getattr(sym, 'ast_node', None)
        return decl is not None and is_exported(decl)

    def _check_funcpointer_named_function(self, expr, fp_type):
        """Construction form 2: a NAMED function in a `FuncPointer<F>` slot.

        `F` is fully known here — it came from the slot — so the overload set is
        resolved AGAINST it: that is what the ruling's "an overload set larger
        than one demands annotation to select" asks for, since the annotation
        that names the FuncPointer is the only way to write `F` down. A name
        with one declaration takes the same path and simply has one candidate.

        Two v1 refusals: a GENERIC function (its address does not exist until a
        type argument picks an instantiation, and nothing here writes one), and
        a body that is not a `sync` context.
        """
        f = self._funcpointer_signature(fp_type)
        name = expr.name
        overloads = self.namespace.lookup_function_overloads(name)
        if not self.namespace.is_accessible(name):
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"function `{name}` is not visible here",
                expr.line, expr.column)
            return None
        want = self._funcpointer_target_signature_key(f)
        matches = []
        generics = []
        for sym in overloads:
            if getattr(sym, 'type_params', None):
                generics.append(sym)
                continue
            if self._funcpointer_decl_signature_key(sym) == want:
                matches.append(sym)
        if len(matches) > 1:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{name}` names {len(matches)} declarations with signature "
                f"`{f}`, so which one this pointer refers to is ambiguous",
                expr.line, expr.column,
                hint="give the overloads distinguishable signatures, or wrap "
                     "the one you mean in a small named function and take a "
                     "pointer to that")
            return None
        if not matches:
            if generics and len(generics) == len(overloads):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{name}` is a generic function, and a generic function "
                    f"has no single address to point at",
                    expr.line, expr.column,
                    hint="a `FuncPointer` names ONE compiled body; write a "
                         "non-generic wrapper that calls the instantiation you "
                         "want, and point at that")
                return None
            have = ", ".join(
                f"`({', '.join(str(p) for p in (s.param_types or []))}) "
                f"{'sync ' if getattr(s, 'is_sync', False) else ''}-> "
                f"{s.return_type or 'Void'}`" for s in overloads[:3])
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"no declaration of `{name}` has signature `{f}` (found {have})",
                expr.line, expr.column,
                hint="a function pointer's signature must match the "
                     "declaration exactly — parameter types and return type, "
                     "with no conversions")
            return None
        sym = matches[0]
        if not self._funcpointer_decl_is_sync(sym):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{name}` is not declared `sync`, so it cannot be a "
                f"`FuncPointer<{f}>`",
                expr.line, expr.column,
                hint=f"write the effect slot — `func {name}(...) sync -> ...` "
                     f"— and the body is checked suspension-free. A bare code "
                     f"address has nowhere to keep the frame a suspending body "
                     f"runs out of, which is why `F` is sync-only")
            return None
        expr.funcpointer_target = fp_type
        expr.funcpointer_symbol = getattr(sym, 'mangled_name', "") or name
        return fp_type

    def _check_funcpointer_captures(self, expr, captures, outer_scope):
        """Refuse a capture in a coerced literal, and recover as capture-less.

        THE property that keeps the bare ABI sound. A coerced literal is
        emitted as `F`'s own function — parameters exactly as written and NO
        environment parameter — so there is physically nowhere for a captured
        value to travel. `captures` is the escaping-capture analysis's own
        result, so `self` and a plainly-named enclosing local are counted here
        by construction (the DF-216a lesson: what matters is what the body
        NAMES, not what a capture list writes).
        """
        if not captures:
            return captures
        names = ", ".join(f"`{n}`" for n in captures)
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"a closure coerced to `FuncPointer` may capture nothing, but this "
            f"one captures {names}",
            expr.line, expr.column,
            hint="a function pointer is a code address and carries no "
                 "environment, so there is nowhere for captured state to "
                 "travel — pass the state through the argument parameter "
                 "instead, or keep it in a `static` the body reads")
        # Recover as the capture-less closure the position demanded: every rule
        # below reacts to a capture, and each would report the same mistake
        # again in the vocabulary of a closure value.
        expr.captures = []
        expr.capture_modes = {}
        return []

    def _analyze_closure_captures(self, body: Block, outer_scope) -> List[str]:
        """Find every variable from an enclosing scope used in the closure body.

        Walks the full expression/statement tree — control flow (if/if-let/
        while/for/match), operators, calls, casts, and nested closures included —
        so a name used anywhere inside the body (e.g. only within a `while` loop,
        which the old analyzer missed) is detected. Nested closures are recursed
        into as well: a name they reference that resolves in an enclosing scope is
        a transitive capture of this closure too. A name is a capture iff it
        resolves in `outer_scope`; the closure's own params/locals do not.

        `self` COUNTS AS A NAME (design 216, DF-216a): the `SelfExpr` arm records
        it, and a method scope defines a binding under that name, so a closure
        body naming `self` inside a method captures the receiver like any other
        enclosing binding. WHICH MODE it is captured in — a BORROW, legal only in
        a non-escaping closure — is decided by the caller, `_check_closure`,
        beside the explicit `[&x]` capture rules it shares that rule with.

        The accumulator is an insertion-ordered dict, NOT a set: the returned
        order becomes the closure environment's field order in the emitted IR, so
        iterating a set of names made the compiler emit different IR for the same
        source on every run (Python randomizes string hashing per process). Order
        is first-use order in the body (design 126 R2).

        TWO CONSUMERS (obligation 1 — a funnel names its entries), and they ask
        the same question for opposite reasons:
          1. THE ESCAPING-CAPTURE ANALYSIS (`_check_closure`, designs 16/29/216)
             — what goes IN the environment, in what mode, and whether a
             frame-pointer capture may escape.
          2. THE `FuncPointer` COERCION (`_check_funcpointer_captures`, design
             226) — whether there is an environment AT ALL. A coerced literal is
             emitted under `F`'s bare ABI with no env parameter, so ANY name
             this walk returns refuses the coercion.
        One walk serves both because both mean "what does the body NAME",
        `self` and a plainly-mentioned enclosing local included — which is
        exactly what a capture LIST does not say (DF-216a). A second walk
        written for the coercion would be a second answer to that question, and
        the position it missed would be a hole with no diagnostic.
        """
        used_names = {}

        def collect_names(expr):
            if expr is None:
                return
            if isinstance(expr, Identifier):
                used_names[expr.name] = None
            elif isinstance(expr, BinaryOp):
                collect_names(expr.left)
                collect_names(expr.right)
            elif isinstance(expr, UnaryOp):
                collect_names(expr.operand)
            elif isinstance(expr, SelfExpr):
                # `self` is a BINDING like any other — the method scope defines
                # it under that name — and a body naming it captures it
                # (design 216, DF-216a). Without this arm SelfExpr fell to the
                # structural tail, which contributes nothing because the node has
                # no fields: `self` never entered `expr.captures`, codegen's
                # closure scope was never given one, and `_generate_self_expr`
                # raised "'self' not found in current scope" for EVERY closure
                # body naming `self`, in every method. The name is a use, and
                # the node has no child to learn that from — which is exactly
                # what the cases above this one are for.
                used_names['self'] = None
            elif isinstance(expr, MoveExpr):
                used_names[expr.variable] = None
            elif isinstance(expr, ReferenceExpr):
                collect_names(expr.expr)
            elif isinstance(expr, CastExpr):
                collect_names(expr.expr)
            elif isinstance(expr, FunctionCall):
                # `f(x)` where `f` is an enclosing closure-typed binding is a
                # capture of `f` (the final `outer_scope.lookup` filter drops
                # top-level function names, which are not locals).
                used_names[expr.name] = None
                for arg in expr.arguments:
                    collect_names(arg.value)
            elif isinstance(expr, MethodCall):
                collect_names(expr.object)
                for arg in expr.arguments:
                    collect_names(arg.value)
            elif isinstance(expr, IfExpr):
                collect_names(expr.condition)
                collect_block(expr.then_branch)
                if expr.else_branch:
                    collect_block(expr.else_branch)
            elif isinstance(expr, IfLetExpr):
                collect_names(expr.optional_expr)
                collect_block(expr.then_branch)
                if expr.else_branch:
                    collect_block(expr.else_branch)
            elif isinstance(expr, WhileExpr):
                collect_names(expr.condition)
                collect_block(expr.body)
            elif isinstance(expr, ForLoop):
                collect_names(expr.iterable)
                collect_block(expr.body)
            elif isinstance(expr, MatchExpr):
                collect_names(expr.matched_expr)
                for arm in expr.arms:
                    # An arm body is a Block as often as it is an expression,
                    # and a guard is ordinary code too. Scanning only the
                    # expression form left a name used inside `case A -> { n }`
                    # uncaptured, and the closure ICE'd on it at codegen.
                    if arm.guard is not None:
                        collect_names(arm.guard)
                    if isinstance(arm.body, Block):
                        collect_block(arm.body)
                    else:
                        collect_names(arm.body)
            elif isinstance(expr, RangeExpr):
                collect_names(expr.start)
                collect_names(expr.end)
            elif isinstance(expr, TupleLiteral):
                for elem in expr.elements:
                    collect_names(elem)
            elif isinstance(expr, TupleIndex):
                collect_names(expr.tuple_expr)
            elif isinstance(expr, ArrayLiteral):
                for elem in expr.elements:
                    collect_names(elem)
            elif isinstance(expr, ArrayIndex):
                collect_names(expr.array_expr)
                collect_names(expr.index)
            elif isinstance(expr, MemberAccess):
                collect_names(expr.object)
            elif isinstance(expr, StructInit):
                for _fname, fval in expr.field_inits:
                    collect_names(fval)
            elif isinstance(expr, EnumInit):
                for arg in expr.arguments:
                    collect_names(arg.value)
            elif isinstance(expr, ForceUnwrap):
                collect_names(expr.expr)
            elif isinstance(expr, NilCoalesce):
                collect_names(expr.expr)
                collect_names(expr.default)
            elif isinstance(expr, OptionalChain):
                collect_names(expr.expr)
            elif isinstance(expr, ClosureExpr):
                # Recurse so a name the nested closure pulls from an enclosing
                # frame is captured here too; its own params/locals won't resolve
                # in outer_scope and are filtered out below.
                collect_block(expr.body)
            else:
                # Everything the cases above do not name. A hand-written walker
                # over an open set of node kinds silently misses the ones nobody
                # thought of, and a MISS here is not a wrong answer but a
                # codegen failure: `{ x in "n={n}" }` never captured `n` (no
                # `StringInterpolation` case) and died with "Undefined variable:
                # n". So the tail is a STRUCTURAL walk, which cannot be
                # incomplete. The cases above stay because each says something
                # the structure does not — a bare name IS a use, a `move`'s
                # subject is a plain string, a call's callee may be a captured
                # closure binding, and a nested closure's parameters are not
                # uses at all.
                collect_structural(expr)

        def collect_structural(node):
            """Walk NODE'S CHILDREN. Never re-dispatches `node` itself, which is
            what keeps the mutual recursion with `collect_names` finite."""
            if node is None or isinstance(node, (SawType, str)):
                return
            if isinstance(node, (list, tuple)):
                for item in node:
                    collect_child(item)
                return
            if isinstance(node, Block):
                collect_block(node)
                return
            if not isinstance(node, (ASTNode, Argument, MatchArm)):
                return
            for f in structural_fields(node):
                collect_child(getattr(node, f.name, None))

        def collect_child(value):
            if isinstance(value, Expression):
                collect_names(value)
            else:
                collect_structural(value)

        def collect_block(block):
            if block is None:
                return
            for stmt in block.statements:
                if isinstance(stmt, ExpressionStatement):
                    collect_names(stmt.expression)
                elif isinstance(stmt, LetStatement):
                    collect_names(stmt.value)
                elif isinstance(stmt, AssignStatement):
                    collect_names(stmt.value)
                    collect_names(stmt.target)
                elif isinstance(stmt, CompoundAssignStatement):
                    collect_names(stmt.value)
                    collect_names(stmt.target)
                elif isinstance(stmt, ReturnStatement):
                    if stmt.value:
                        collect_names(stmt.value)
                elif isinstance(stmt, GuardLetStatement):
                    collect_names(stmt.optional_expr)
                    collect_block(stmt.else_branch)
                elif isinstance(stmt, BreakStatement):
                    if stmt.value:
                        collect_names(stmt.value)
                elif isinstance(stmt, (WhileExpr, ForLoop)):
                    collect_names(stmt)
                else:
                    # Any other statement — a bare `if`/`match`, a `lend`, a
                    # `try` — through the same structural tail.
                    collect_structural(stmt)
            if block.final_expr:
                collect_names(block.final_expr)

        collect_block(body)
        captures = []
        for name in used_names:
            if outer_scope.lookup(name):
                captures.append(name)
        return captures

    # ===== Try Expression Checking =====

    def _check_try_expr(self, expr: TryExpr) -> Optional[SawType]:
        """Check a try expression: try expr, try? expr, or try! expr.

        - try expr: Unwraps Ok, propagates Err (function must return Result<_, E>)
        - try? expr: Converts Result<T, E> to T? (returns None on Err)
        - try! expr: Unwraps Ok, panics on Err (like force unwrap)
        """
        inner_type = self._check_expression(expr.expr)
        if inner_type is None:
            return None

        # Must be a Result<T, E>
        if not inner_type.is_result():
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`try` requires a Result type, got `{inner_type}`",
                expr.line, expr.column
            )
            return None

        # Record the CONCRETE Result type for codegen. A generic call's declared
        # return type (e.g. `Result<T, E>`) arrives as a STRUCT-kind
        # `Result<Int, Int>`; resolve it to its ENUM form so codegen can select
        # the right monomorphized instantiation by NAME. Without this, the try
        # codegen falls back to matching by LLVM layout, which is ambiguous:
        # `Result<Int, Int>` and `Result<String, E>` share the identical
        # `{ i32, [8 x i8] }` layout, so the wrong Ok/Err payload type would be
        # used (extracting an Int as a String pointer -> crash). Mirrors the
        # `match` path's `matched_enum_type` annotation (brief 36, L7).
        expr.result_enum_type = self._resolve_type(inner_type)

        ok_type = inner_type.unwrap_result_ok()
        err_type = inner_type.unwrap_result_err()

        if expr.variant == "optional":
            self._reject_route_clause(expr, "try?")
            # try? returns T?
            return SawType(TypeKind.OPTIONAL, inner_type=ok_type)

        elif expr.variant == "force":
            self._reject_route_clause(expr, "try!")
            # try! returns T (panics on Err)
            return ok_type

        else:  # "propagate"
            # design 234 §3: the ROUTING clause converts the error CHANNEL, and
            # it does so BEFORE propagation — so everything downstream (the
            # signature check, the enclosing catch's union, the suspending
            # one-fence rule) sees the TARGET type and needs no special case.
            routed = self._check_try_routing(expr, err_type)
            if routed is None:
                # A malformed clause already reported. Say nothing further: what
                # this `try` propagates is the target the author named, and
                # validating the SOURCE type against the signature would add a
                # second diagnostic about a type they did not mean to send.
                return ok_type
            err_type = routed

            # If there's an inline catch block, check it
            if expr.catch_block:
                return self._check_try_with_catch(expr, ok_type, err_type)

            # Otherwise, try expr propagates - function must return Result<_, E>
            self._validate_error_propagation(err_type, expr.line, expr.column, expr)
            return ok_type

    def _reject_route_clause(self, expr: TryExpr, spelling: str):
        """`try!` / `try?` never take design 234's routing clause: neither
        PROPAGATES, so there is no error channel to convert."""
        if expr.route_path is None:
            return
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"`{spelling}` cannot take a routing clause — "
            f"`{spelling}` does not propagate the error, so there is no error "
            f"channel to convert",
            expr.line, expr.column,
            hint=f"drop the `(as {'.'.join(expr.route_path)})`, or write a "
                 f"propagating `try` if the error should leave this function"
        )

    def _check_try_routing(self, expr: TryExpr,
                           err_type: SawType) -> Optional[SawType]:
        """Design 234 §3 — resolve `try(as ErrorType.Case) f()`.

        THE ONE ENTRY POINT for the routing clause, on both the checking and the
        stamping side. Every position a `try` may appear in reaches it through
        `_check_try_expr` — statement, `let` initializer, argument, string
        interpolation, `match` subject, `??` right operand, a suspending body's
        ANF hoist, and inside a `try { } catch { }` block — because the clause
        rides the `TryExpr` NODE rather than any one syntactic context. Codegen
        has the mirror chokepoint in `_generate_try_propagate`.

        No auto-lift, no trait, no candidate search: the named case must have a
        SINGLE payload the source error type can fill, checked here and done.

        Returns the error type that PROPAGATES: the unchanged source type when
        no clause was written, the routing TARGET when the clause is well
        formed, and None when it is not — a malformed clause has reported once
        already, and its caller must not go on to check the SOURCE type against
        the signature, which would add a second diagnostic about a type the
        author did not mean to send.
        """
        if expr.route_path is None:
            return err_type
        if expr.catch_block is not None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "a `try` with a routing clause cannot also carry a `catch` — "
                "route the error onward, or handle it here, not both",
                expr.line, expr.column,
                hint="drop the `(as ...)` clause to handle the error in the "
                     "`catch`, or drop the `catch` to route it to the caller"
            )
            return None

        *type_segments, case_name = expr.route_path
        type_name = type_segments[-1]
        qualified = ".".join(type_segments) if len(type_segments) > 1 else None
        written = ".".join(expr.route_path)

        enum_info = self.get_enum_info(type_name, qualified_path=qualified)
        if enum_info is None:
            self._error(
                ErrorKind.UNKNOWN_TYPE,
                f"`try(as {written})`: `{'.'.join(type_segments)}` is not an "
                f"enum in scope — a routing clause names an enum case",
                expr.line, expr.column,
                hint="the target of a routing clause is a payload-carrying "
                     "case of an error enum, e.g. "
                     "`enum LocalError { case Alloc(e: AllocError) }`"
            )
            return None

        if case_name not in enum_info.variants:
            known = ", ".join(f"`{v}`" for v in enum_info.variant_order) or "none"
            self._error(
                ErrorKind.UNKNOWN_TYPE,
                f"`try(as {written})`: enum `{type_name}` has no case "
                f"`{case_name}`",
                expr.line, expr.column,
                hint=f"cases of `{type_name}`: {known}"
            )
            return None

        payload = self._variant_payload_types(enum_info, case_name)
        if len(payload) != 1:
            shape = ("carries no payload" if not payload
                     else f"carries {len(payload)} payload fields")
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`try(as {written})`: case `{case_name}` {shape}, so it "
                f"cannot carry the error — a routing target holds exactly one "
                f"value",
                expr.line, expr.column,
                hint=f"declare it as `case {case_name}(e: {err_type})`, or "
                     f"route to a case that already carries one value"
            )
            return None

        payload_type = payload[0][1]
        if not self._transfer_compatible(err_type, payload_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`try(as {written})`: case `{case_name}` carries "
                f"`{payload_type}`, but this call fails with `{err_type}`",
                expr.line, expr.column,
                hint=f"route to a case whose payload is `{err_type}`, or widen "
                     f"the case's payload"
            )
            return None

        target = self._resolve_type(SawType(TypeKind.ENUM, enum_name=type_name,
                                            symbol=enum_info))
        expr.route_target = target
        expr.route_case = case_name
        return target

    def _validate_error_propagation(self, err_type: SawType, line: int, column: int, expr=None):
        """Validate that error can be propagated from current function or to enclosing catch."""
        # If we're inside a try-catch block, errors go to the catch block
        if self.in_try_catch_block:
            # Track the error type for the enclosing try-catch
            if hasattr(self, '_try_catch_error_types') and self._try_catch_error_types is not None:
                self._try_catch_error_types.append(err_type)
            return  # OK - error will be caught by enclosing try-catch

        # design 213 entry point 4: an error raised inside a closure propagates
        # out of the CLOSURE, so the target is the closure's return type. Reading
        # the enclosing named function's instead accepted a `try` in an
        # `Int`-returning closure whenever the OUTER function returned a Result,
        # and codegen then emitted the Result out of an `i64` function ("value
        # doesn't match function result type 'i64'").
        target = self._return_target()
        if target is not None:
            if target.expected is None:
                # Return type not known yet — replay once the body has been
                # checked and it is (see `_check_closure`).
                target.pending_try.append((err_type, line, column, expr))
                return
            expected_return = self._resolve_type(target.expected)
        elif self.current_function:
            expected_return = self.current_function.return_type
        elif self.current_method:
            expected_return = self.current_method.return_type
        else:
            expected_return = None

        self._validate_error_propagation_against(
            expected_return, err_type, line, column, expr)

    def _validate_error_propagation_against(self, expected_return, err_type: SawType,
                                            line: int, column: int, expr=None):
        """Validate a propagated error against an ALREADY-RESOLVED return target.

        Split out of `_validate_error_propagation` (design 213) so a closure
        whose return type is still being inferred can replay its `try`s once the
        body has settled the type.
        """
        # Name what the `try` is actually leaving, so a closure's diagnostic
        # does not point the reader at the enclosing function's signature.
        what = "closure" if self._return_target() is not None else "function"
        if expected_return is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`try` can only propagate errors from functions/methods",
                line, column
            )
            return

        if not expected_return.is_result():
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`try` cannot propagate errors from a {what} returning `{expected_return}` (must return Result)",
                line, column,
                hint="use `try?` to convert to optional, or `try!` to force unwrap, or add a `catch` block"
            )
            return

        expected_err = expected_return.unwrap_result_err()
        if self._types_compatible(err_type, expected_err):
            return  # passthrough (includes an already-erased box == box)
        # Erased Result (design 56): the function returns `Result<_, Box<any
        # Trait>>` and this callee's error is a concrete conformer — re-box it at
        # the propagation edge. Stamp the erasure for codegen.
        trait = self.namespace._erased_trait_of(expected_err)
        if trait is not None and self._can_erase_to(err_type, trait):
            if expr is not None:
                expr.erase_propagate = {
                    'trait': trait,
                    'concrete': err_type,
                    'allocator': SawType(TypeKind.STRUCT, struct_name="GlobalAllocator"),
                }
            return
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"cannot propagate error of type `{err_type}` from function returning `Result<_, {expected_err}>`",
            line, column
        )

    def _check_try_with_catch(self, expr: TryExpr, ok_type: SawType, err_type: SawType) -> Optional[SawType]:
        """Check try expression with inline catch block."""
        from .core import VariableInfo, Scope

        # Create scope for catch block with 'error' binding
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        # Add implicit 'error' variable with the error type
        self.current_scope.define(
            "error",
            VariableInfo(
                type=err_type,
                mutable=False,
                line=expr.catch_block.line,
                column=expr.catch_block.column
            )
        )

        # Check catch block
        catch_type = self._check_block(expr.catch_block)
        self.current_scope = old_scope

        # Types must be compatible (catch must return same type as ok_type)
        if catch_type and not self._types_compatible(catch_type, ok_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"catch block returns `{catch_type}` but try expression expects `{ok_type}`",
                expr.catch_block.line, expr.catch_block.column
            )

        return ok_type

    def _check_try_catch_expr(self, expr: TryCatchExpr) -> Optional[SawType]:
        """Check a try-catch block expression: try { ... } catch { ... }"""
        from .core import VariableInfo, Scope

        # Set flag so try expressions know they're inside a try-catch
        old_in_try_catch = self.in_try_catch_block
        self.in_try_catch_block = True

        # Track error types from try expressions in this block
        old_try_catch_error_types = getattr(self, '_try_catch_error_types', None)
        self._try_catch_error_types = []

        # Check try block
        try_type = self._check_block(expr.try_block)

        # Collect unique error types
        error_types = self._try_catch_error_types
        unique_error_types = []
        for err_type in error_types:
            # Check if we already have this type
            is_dup = False
            for existing in unique_error_types:
                if self._types_compatible(err_type, existing):
                    is_dup = True
                    break
            if not is_dup:
                unique_error_types.append(err_type)

        # Determine the error type for the catch block
        if len(unique_error_types) == 0:
            error_type = SawType(TypeKind.STRUCT, struct_name="Error")  # Fallback
        elif len(unique_error_types) == 1:
            error_type = unique_error_types[0]  # Single error type
        else:
            # Multiple error types - create a union enum
            error_type = self._create_error_union_type(unique_error_types, expr)

        # Store the error type on the expression for codegen
        expr.error_type = error_type
        expr.error_types = unique_error_types

        # Restore tracking
        self._try_catch_error_types = old_try_catch_error_types

        # Restore flag before checking catch (catch is not inside try-catch context)
        self.in_try_catch_block = old_in_try_catch

        # Create scope for catch block with 'error' binding
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        # Add implicit 'error' variable with the actual error type
        error_name = expr.error_binding or "error"
        self.current_scope.define(
            error_name,
            VariableInfo(
                type=error_type,
                mutable=False,
                line=expr.catch_block.line,
                column=expr.catch_block.column
            )
        )

        # Check catch block
        catch_type = self._check_block(expr.catch_block)
        self.current_scope = old_scope

        # Types must be compatible
        if try_type and catch_type and not self._types_compatible(try_type, catch_type):
            # Allow optional wrapping - if one returns T and other returns T?, wrap
            if try_type.is_optional() and not catch_type.is_optional():
                pass  # catch_type will be wrapped
            elif catch_type.is_optional() and not try_type.is_optional():
                pass  # try_type will be wrapped
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"try and catch blocks have incompatible types: `{try_type}` vs `{catch_type}`",
                    expr.line, expr.column
                )

        return try_type or catch_type

    def _create_error_union_type(self, error_types: List[SawType], expr) -> SawType:
        """Create a union enum type for multiple error types.

        Creates an enum like:
            enum _CatchError_123 {
                case ParseError(value: ParseError),
                case IoError(value: IoError)
            }

        This allows using match in the catch block to differentiate errors.
        """
        # Build variants - each error type becomes a variant with 'value' field
        variants = {}
        variant_order = []
        for err_type in error_types:
            # Get variant name from the type
            if err_type.kind == TypeKind.STRUCT:
                variant_name = err_type.struct_name
            elif err_type.kind == TypeKind.ENUM:
                variant_name = err_type.enum_name
            else:
                variant_name = str(err_type)

            variants[variant_name] = [("value", err_type)]
            variant_order.append(variant_name)

        # THE NAME IS THE CONTENT, and it has to be (design 126 R2, finished).
        # This name reaches codegen and the emitted type table, so anything
        # POSITIONAL in it makes the compiler's output depend on how much was
        # compiled before this file. It was `id(expr)` once, which differed run
        # to run; then `expr.node_id`, which is stable across two FRESH
        # processes and shifts the moment something is compiled ahead of it —
        # invisible until design 246 unit B made a payload-carrying enum an
        # IDENTIFIED LLVM type, at which point the name landed in the IR text
        # and `reemitdiff` caught it on the second in-process compile.
        #
        # The variant SEQUENCE identifies the union exactly: a variant name IS
        # its error type's identity, so two unions with the same sequence hold
        # the same payloads in the same order — the same type, with the same
        # tags — and two that differ anywhere get different names. Two catch
        # sites raising the same errors in the same order now SHARE one union,
        # which is a deduplication rather than a collision.
        union_name = "_CatchError_" + "_".join(variant_order)

        # Register the enum in namespace
        union_enum = EnumSymbol(
            variants=variants,
            variant_order=variant_order,
            type_params=[],
            visibility=Visibility.PRIVATE
        )
        self.namespace.register_enum(union_name, union_enum)

        return SawType(TypeKind.ENUM, enum_name=union_name, symbol=union_enum)
