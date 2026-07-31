"""
Saw Language Type Checker
Performs type checking and semantic analysis on the AST.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from ast_nodes import (
    Program, Function, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    WhileExpr, BreakStatement, ContinueStatement, ForLoop, RangeExpr,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation, Identifier,
    BinaryOp, UnaryOp, MoveExpr, CastExpr, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex,
    MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    GuardLetStatement,
    Struct, StructField,
    Enum, EnumVariant, EnumInit, MatchExpr, MatchArm,
    Extension, Method, MethodCall, SelfExpr,
    Trait, TraitMethod, AssociatedType, TypeAssignment, TypeDefinition,
    ExternFunction, ExternBlock,
    SawType, TypeKind, Parameter, Argument, TypeParameter,
    ClosureExpr, ClosureParam,
    ImportDecl, Visibility
)
from errors import ErrorReporter, ErrorKind
from namespace import (
    Namespace, SymbolKind,
    FunctionSymbol, StructSymbol, EnumSymbol, TraitSymbol, TypeAliasSymbol,
    TraitMethodSymbol
)
from .types import TypeUtilsMixin
from .registration import RegistrationMixin
from .statements import StatementsMixin
from .expressions import ExpressionsMixin
from .effects import EffectsMixin


@dataclass
class VariableInfo:
    """Information about a variable in scope."""
    type: SawType
    mutable: bool
    line: int
    column: int


class Scope:
    """A lexical scope containing variable bindings."""

    def __init__(self, parent: Optional['Scope'] = None):
        self.parent = parent
        self.variables: Dict[str, VariableInfo] = {}

    def define(self, name: str, info: VariableInfo) -> bool:
        """Define a variable in this scope. Returns False if already defined."""
        if name in self.variables:
            return False
        self.variables[name] = info
        return True

    def lookup(self, name: str) -> Optional[VariableInfo]:
        """Look up a variable, checking parent scopes."""
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def lookup_local(self, name: str) -> Optional[VariableInfo]:
        """Look up a variable only in this scope."""
        return self.variables.get(name)


class TypeChecker(ExpressionsMixin, StatementsMixin, RegistrationMixin, TypeUtilsMixin, EffectsMixin):
    """Type checks a Saw program."""

    def __init__(self, reporter: ErrorReporter, freestanding: bool = False):
        self.reporter = reporter
        # Freestanding profile (design 19/20): gates hosted-only facilities such
        # as Float formatting in print (dtoa is not available without libc).
        self.freestanding = freestanding
        self.current_scope: Scope = Scope()
        self.current_function: Optional[Function] = None
        self.current_method: Optional['Method'] = None  # Track current method for 'self'
        # Type substitution map for specialized extensions (e.g., {"T": String})
        self.current_type_subst: Dict[str, SawType] = {}
        # Track return statements found in current function
        self.found_return_with_value: bool = False
        # Track loop nesting depth for break/continue validation
        self.loop_depth: int = 0
        # Unsafe surface (design 81). `_unsafe_marker_depth` > 0 while checking
        # inside an `unsafe <expr>` marker (or an `unsafe`-marked store);
        # `_current_fn_unsafe_domain` is True inside a function/method whose own
        # signature carries a raw pointer (the marked domain — everything free);
        # `_unsafe_ops_seen` is a monotonic counter of raw-pointer operations
        # encountered, used to detect a marker that covers nothing unsafe.
        self._unsafe_marker_depth: int = 0
        self._current_fn_unsafe_domain: bool = False
        self._unsafe_ops_seen: int = 0
        # >0 while checking the operand of a cast whose target is a raw pointer
        # (`(block + 8) as UnsafePointer<Int>`). The `UnsafePointer` type is named
        # IN the expression, so the pointer flow is already visible/greppable — a
        # pointer op under such a cast needs no `unsafe` marker.
        self._ptr_cast_depth: int = 0
        # Track break value types for each loop level
        # Each entry is (expected_type: Optional[SawType], is_infinite: bool, has_break: bool)
        self.loop_break_info: List[Tuple[Optional[SawType], bool, bool]] = []
        # Per-function, scope-aware move state for use-after-move detection.
        # Keyed by id() of the binding's VariableInfo (its identity), so that
        # same-named bindings in different functions/scopes never interact and
        # a `let`/`var` shadow gets fresh state. The VariableInfo object is kept
        # alive in the value tuple, so the id() key can never be reused.
        # value = (var_info, name, move_line, move_column)
        self.moved_bindings: Dict[int, Tuple['VariableInfo', str, int, int]] = {}
        # Structs whose copy() is compiler-derived (memberwise), checked for
        # NoCopy fields after all conformances are registered.
        self._derived_copy_structs: set[str] = set()
        # Structs/enums whose equals() (==) is compiler-derived (design 32),
        # checked for non-Equatable fields/payloads after all conformances are
        # registered.
        self._derived_equals_types: set[str] = set()
        # Structs/enums whose compare() (< <= > >=) is compiler-derived
        # (design 48), checked for non-Comparable fields/payloads and the
        # Equatable requirement after all conformances are registered.
        self._derived_compare_types: set[str] = set()
        # Structs/enums whose hash() is compiler-derived (design 48), checked for
        # non-Hashable fields/payloads after all conformances are registered.
        self._derived_hash_types: set[str] = set()
        # Every type declaring `extension T: Comparable` / `Hashable` (derived or
        # custom): each must also conform to Equatable (the "requires Equatable"
        # rule), verified after all conformances are registered.
        self._comparable_types: set[str] = set()
        self._hashable_types: set[str] = set()
        # Track if we're inside a try-catch block (errors go to catch, not caller)
        self.in_try_catch_block: bool = False

        # design 22 effect system: whole-program suspend analysis state.
        self._effect_init()

        # design 58: whole-program C-export symbol table for hygiene checks
        # (duplicate exported symbols across the compilation unit). Accumulated
        # across every module the shared checker instance visits. Maps the
        # requested C symbol -> (declaration name, line, column, source_file).
        self._export_symbol_table: Dict[str, Tuple[str, int, int, Optional[str]]] = {}

        # Unified namespace (Phase 0 of module system)
        # Populated in parallel with legacy dicts during migration
        self.namespace = Namespace()

        # Current module path during multi-module type checking
        self.current_module_path: Tuple[str, ...] = ()

        # Register built-in functions
        self._register_builtins()

    def _get_current_source_file(self) -> Optional[str]:
        """Get the source file from the current method or function context."""
        if self.current_method and hasattr(self.current_method, 'source_file'):
            return self.current_method.source_file or None
        if self.current_function and hasattr(self.current_function, 'source_file'):
            return self.current_function.source_file or None
        return None

    # ------------------------------------------------------------------ #
    # Member visibility (design 80) — module identity for the field/method gate.
    #
    # std/builtin declarations are merged into ONE AST for codegen (the prelude
    # "bypass"), so their registration module_path is `()` — indistinguishable
    # from user code. For the ACCESS gate we key each declaration's defining
    # module on its SOURCE FILE: std/builtin form the single distinguished module
    # `("<std>",)`; user code keeps its real module_path. This kills the prelude
    # bypass for visibility only (codegen's compiler-known-ness is untouched) and
    # enforces the security-relevant boundary: user code cannot reach a private
    # std member (e.g. `Vector.length`), while std's own files freely cross-
    # reference each other (one std module — the standard library is one unit).
    # ------------------------------------------------------------------ #
    def _vis_module_for_source(self, source_file: Optional[str]) -> Tuple[str, ...]:
        import os
        if not source_file:
            return self.current_module_path
        try:
            norm = os.path.abspath(source_file)
        except Exception:
            return self.current_module_path
        std_prefix = getattr(self, '_std_dir_prefix', None)
        if std_prefix is None:
            sawc_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            std_prefix = os.path.join(sawc_dir, 'std') + os.sep
            self._std_dir_prefix = std_prefix
        base = os.path.basename(norm)
        if norm.startswith(std_prefix) or base == 'builtin.saw':
            return ("<std>",)
        return self.current_module_path

    def _accessor_vis_module(self) -> Tuple[str, ...]:
        """The defining module of the code currently being type-checked (the
        accessor), for the member-visibility gate."""
        return self._vis_module_for_source(self._get_current_source_file())

    def _in_synthesized_context(self) -> bool:
        """Whether the code currently being checked is compiler-synthesized
        (coroutine-transform output). Such code accesses std/frame internals by
        construction and is EXEMPT from the member-visibility gate (design 80) —
        the gate enforces source-level access only. Provenance-based, not by name."""
        if self.current_method is not None and getattr(
                self.current_method, 'is_synthesized', False):
            return True
        if self.current_function is not None and getattr(
                self.current_function, 'is_synthesized', False):
            return True
        return False

    # ===== Unsafe surface (design 81) =====

    def _type_tree_has_pointer(self, t) -> bool:
        """Whether a type mentions a raw pointer (`UnsafePointer<T>` /
        `UnsafeConstPointer<T>`, `TypeKind.POINTER`) ANYWHERE in its tree —
        directly, or nested in an optional/array/tuple/generic-arg/closure. Used
        to decide whether a function's signature carries an `Unsafe*` type (and
        is therefore in the marked domain)."""
        if t is None:
            return False
        if t.kind == TypeKind.POINTER:
            return True
        if getattr(t, 'inner_type', None) and self._type_tree_has_pointer(t.inner_type):
            return True
        if getattr(t, 'array_element_type', None) and self._type_tree_has_pointer(t.array_element_type):
            return True
        for ta in (getattr(t, 'type_args', None) or []):
            if self._type_tree_has_pointer(ta):
                return True
        for et in (getattr(t, 'element_types', None) or []):
            if self._type_tree_has_pointer(et):
                return True
        for pt in (getattr(t, 'param_types', None) or []):
            if self._type_tree_has_pointer(pt):
                return True
        if getattr(t, 'func_return_type', None) and self._type_tree_has_pointer(t.func_return_type):
            return True
        return False

    def _signature_unsafe_domain(self, param_types, return_type) -> bool:
        """A function/method is in the UNSAFE DOMAIN when its own signature —
        any parameter type or the return type — carries a raw pointer (design
        81). Inside such a function raw-pointer operations are free: the pointer
        type is already visible at the signature. `self` (a struct receiver) is
        never a raw pointer, so a pointer FIELD does not put the method in the
        domain (the field decl is its own visible marker)."""
        for pt in (param_types or []):
            if self._type_tree_has_pointer(pt):
                return True
        return self._type_tree_has_pointer(return_type)

    def _struct_has_pointer_field(self, struct_name) -> bool:
        """Whether a struct declares a field whose type carries a raw pointer
        (design 81). A `self`-receiver method of such a struct is in the unsafe
        domain: the pointer field's decl is the visible marker for operations on
        it. Extension of a primitive/non-struct receiver has no such field."""
        if not struct_name:
            return False
        info = self.get_struct_info(struct_name)
        if info is None:
            return False
        for _fname, ftype in info.fields.items():
            if self._type_tree_has_pointer(ftype):
                return True
        return False

    def _note_unsafe_op(self, expr, what: str) -> None:
        """Record (and, when required, reject) a raw-pointer operation whose
        pointer value flows INVISIBLY (design 81): a deref/index/write, pointer
        arithmetic, or a pointer produced by a call. The `unsafe` marker, an
        enclosing cast that names a pointer type, the enclosing function being in
        the unsafe domain, or compiler-synthesized provenance (design 80) each
        satisfy the requirement; otherwise it is a clean error naming the
        operation."""
        self._unsafe_ops_seen += 1
        if self._unsafe_marker_depth > 0:
            return
        if self._ptr_cast_depth > 0:
            # The pointer op is the operand of a cast that names `UnsafePointer`
            # in source — already visible/greppable, no marker required.
            return
        if self._current_fn_unsafe_domain:
            return
        if self._in_synthesized_context():
            return
        if getattr(expr, '_unsafe_reported', False):
            return
        expr._unsafe_reported = True
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{what} requires the `unsafe` marker",
            getattr(expr, 'line', 0), getattr(expr, 'column', 0),
            hint="prefix the expression with `unsafe` (e.g. `let p = unsafe "
                 "A().alloc(size, align)`, `unsafe ptr[0]`) — the raw pointer "
                 "flows with no `UnsafePointer` type visible at this site; or put "
                 "an `Unsafe*` type in this function's signature to enter the "
                 "marked domain",
        )

    def _member_gate_allows(self, def_module: Tuple[str, ...],
                            visibility: Visibility) -> bool:
        """Whether the code currently being checked may reach a member with the
        given defining module + visibility (design 80). Same-module access is
        always allowed; cross-module follows the top-level visibility rules."""
        accessor = self._accessor_vis_module()
        if def_module == accessor:
            return True
        return self.namespace.check_visibility(
            visibility, symbol_module=def_module, accessor_module=accessor,
            package_root=getattr(self.namespace, 'package_root', ()))

    def _vis_word(self, visibility: Visibility) -> str:
        return {
            Visibility.PUBLIC: "public",
            Visibility.PACKAGE: "public(package)",
            Visibility.PARENT: "public(parent)",
            Visibility.PRIVATE: "private",
        }.get(visibility, "private")

    def _error(self, kind: ErrorKind, message: str, line: int, column: int,
               hint: Optional[str] = None, source_file: Optional[str] = None):
        """Report an error with automatic source file detection.

        If source_file is not provided, attempts to determine it from the
        current method or function context.
        """
        if source_file is None:
            source_file = self._get_current_source_file()
        self.reporter.error(kind, message, line, column, hint, source_file)

    def _warning(self, kind: ErrorKind, message: str, line: int, column: int,
                 hint: Optional[str] = None, source_file: Optional[str] = None):
        """Report a warning with automatic source file detection."""
        if source_file is None:
            source_file = self._get_current_source_file()
        self.reporter.warning(kind, message, line, column, hint, source_file)

    def _validate_exports(self, program: Program):
        """`export` statements are only permitted in init.saw facade files.

        Applied on every compile path (single-file and per-module), so a stray
        `export` in a regular file is diagnosed regardless of whether the file
        also uses imports/modules.
        """
        exports = getattr(program, 'exports', [])
        if not exports:
            return
        source_path = getattr(program, 'source_path', None)
        if source_path is None:
            # Provenance unknown (e.g. an imported module AST that was not tagged
            # with its path); the entry file always carries source_path, so this
            # only skips imported modules — matching prior per-module behavior.
            return
        if source_path.endswith('init.saw'):
            return
        for exp in exports:
            self.reporter.error(
                ErrorKind.SYNTAX,
                "`export` statements are only allowed in init.saw files",
                exp.line, exp.column,
                hint="use `public` visibility modifier to expose symbols from regular modules"
            )

    def check(self, program: Program, require_main: bool = True) -> bool:
        """Type check the entire program. Returns True if no errors.

        Args:
            program: The AST to type check
            require_main: If True, error if no main() function (default for executables).
                         Set to False for library/object file compilation.
        """
        # Validate: exports are only allowed in init.saw files
        self._validate_exports(program)

        # First pass: register type definitions (aliases)
        for type_def in program.type_definitions:
            self._register_type_definition(type_def)

        # Second pass: collect struct definitions
        for struct in program.structs:
            self._register_struct(struct)

        # Third pass: collect enum definitions
        for enum in program.enums:
            self._register_enum(enum)

        # Fourth pass: collect trait definitions
        for trait in program.traits:
            self._register_trait(trait)

        # Fifth pass: register extensions and their methods
        for extension in program.extensions:
            self._register_extension(extension)

        # Fifth-a.5 pass: validate `any Trait` existentials in all declared
        # signatures/fields (design 51 object safety + unsized discipline). Runs
        # after traits are registered so object safety is decidable.
        self._validate_existentials_in_program(program)

        # Fifth-b pass: check resource management containment rules
        self._check_no_copy_containment()
        self._check_implicit_copy_containment()
        self._check_explicit_copy_containment()
        self._check_copy_trait_exclusivity()
        self._check_derivable_copy()
        self._check_derivable_equals()
        self._check_derivable_compare()
        self._check_derivable_hash()
        self._check_ord_hash_require_equatable()
        self._check_deinit_containment()

        # Register extern functions (FFI)
        for extern_block in program.extern_blocks:
            for extern_func in extern_block.functions:
                self._register_extern_function(extern_func)

        # Sixth pass: collect function signatures
        for func in program.functions:
            self._register_function(func)

        # Sixth-b pass: register module-level statics (design 41). After
        # structs/enums/functions so a const initializer may reference them.
        for static in getattr(program, 'statics', []):
            self._register_static(static)

        # Overloading (design 55): now that every function/method signature is
        # registered, assign each member of a 2+ overload set its type-signature
        # codegen symbol (stamped on both the symbol and its AST node).
        self._stamp_overload_symbols()

        # design 58: validate @export / @section on functions and statics.
        self._check_attribute_semantics(program)

        # Check for main function (only required for executables)
        if require_main and not self.namespace.has_function("main"):
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                "no `main` function found",
                1, 1,
                hint="add a `func main() { }` function as the entry point, or use -c to compile as object file"
            )

        # Seventh pass: type check function bodies
        for func in program.functions:
            self._check_function(func)

        # Eighth pass: type check method bodies
        for extension in program.extensions:
            self._check_extension(extension)

        # design 53: type-check top-level static_assert conditions (stamps the
        # annotations the codegen const evaluator consumes; surfaces type errors).
        for sa in getattr(program, 'static_asserts', []):
            self._check_static_assert(sa)

        # Ninth pass: whole-program `sync` effect analysis (design 22).
        self.finalize_effects()

        return not self.reporter.has_errors()

    # ------------------------------------------------------------------ design 58
    # C-export signature whitelist. Function parameters accept these scalar
    # kinds; the return additionally accepts Void and Never (noreturn). Everything
    # else — Bool, String, Optional, Result/enum, tuple, closure, by-value struct,
    # array, existential, reference — is rejected (pass UnsafePointer<S> for an
    # aggregate). Bool is REJECTED in v1: the extern-import path lowers it as a
    # bare `i1`, which does not match the platform C `_Bool` ABI, and no stdlib
    # extern actually passes a Bool, so there is no sound precedent to mirror.
    _EXPORT_FN_SCALAR_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
        TypeKind.FLOAT, TypeKind.POINTER,
    })
    # Exported STATIC data has no calling convention, so the whitelist relaxes to
    # scalars (no pointer — a static pointer to nothing is not meaningful data),
    # plus arrays and structs recursively built from whitelisted fields.
    _EXPORT_STATIC_SCALAR_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
        TypeKind.FLOAT,
    })

    def _describe_type_for_export(self, t: SawType) -> str:
        """Short human phrase for a non-whitelisted export type."""
        resolved = self._resolve_type_alias(t)
        k = resolved.kind
        phrases = {
            TypeKind.BOOL: "`Bool`",
            TypeKind.STRING: "`String`",
            TypeKind.OPTIONAL: "an optional (`T?`)",
            TypeKind.TUPLE: "a tuple",
            TypeKind.FUNCTION: "a closure",
            TypeKind.ARRAY: "an array",
            TypeKind.STRUCT: f"the by-value struct `{resolved.struct_name}`",
            TypeKind.ENUM: f"the enum `{resolved.enum_name}`",
            TypeKind.EXISTENTIAL: "an `any` existential",
            TypeKind.REFERENCE: "a reference",
        }
        return phrases.get(k, f"`{k.name}`")

    def _export_fn_type_ok(self, t: SawType, *, is_return: bool) -> bool:
        resolved = self._resolve_type_alias(t)
        k = resolved.kind
        if k in self._EXPORT_FN_SCALAR_KINDS:
            return True
        if is_return and k in (TypeKind.VOID, TypeKind.NEVER):
            return True
        return False

    def _export_static_type_ok(self, t: SawType, _seen=None) -> bool:
        resolved = self._resolve_type_alias(t)
        k = resolved.kind
        if k in self._EXPORT_STATIC_SCALAR_KINDS:
            return True
        if k == TypeKind.ARRAY:
            return self._export_static_type_ok(resolved.array_element_type)
        if k == TypeKind.STRUCT:
            # Recurse into fields; guard against cyclic struct graphs.
            seen = _seen or set()
            if resolved.struct_name in seen:
                return True
            seen = seen | {resolved.struct_name}
            info = self.get_struct_info(resolved.struct_name)
            if info is None or getattr(info, 'type_params', None):
                return False  # unknown or generic struct: not a fixed C layout
            for _fname, ftype in info.fields.items():
                if not self._export_static_type_ok(ftype, seen):
                    return False
            return True
        return False

    def _register_export_symbol(self, sym: str, node) -> None:
        """Symbol hygiene (design 58): reserved-symbol collision + duplicate
        exported-symbol detection across the whole compilation unit."""
        src = getattr(node, 'source_file', None)
        if sym == "main" or sym.startswith("saw_") or sym.startswith("__saw_"):
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"`@export` symbol `{sym}` collides with a reserved runtime "
                f"symbol (`main`, `saw_*`, `__saw_*`)",
                node.line, node.column,
                hint="choose a different exported symbol name via "
                     "`@export(\"other_name\")`",
                source_file=src)
            return
        prev = self._export_symbol_table.get(sym)
        if prev is not None:
            pname, pline, _pcol, _pfile = prev
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"duplicate `@export` symbol `{sym}` (already exported by "
                f"`{pname}` at line {pline})",
                node.line, node.column,
                hint="an unmangled C symbol must be unique across the program; "
                     "give one an explicit `@export(\"other_name\")`",
                source_file=src)
            return
        self._export_symbol_table[sym] = (
            getattr(node, 'name', sym), node.line, node.column, src)

    def _check_attribute_semantics(self, program: Program) -> None:
        """design 58 Part 2/3: validate @export and @section semantics on the
        functions and statics of one module (parser already enforced grammar +
        position). Suspension-freedom of an exported function is checked by the
        effect machinery, which treats it as a `sync` root (see effects.py)."""
        from ast_nodes import is_exported, export_symbol, section_name

        for func in program.functions:
            sec = section_name(func)
            if sec is not None and sec.strip() == "":
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    "`@section` name must be a non-empty string",
                    func.line, func.column, source_file=func.source_file)
            if not is_exported(func):
                continue
            sym = export_symbol(func)
            if func.type_params:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot `@export` the generic function `{func.name}` — a C "
                    f"symbol has no type parameters",
                    func.line, func.column,
                    hint="export a concrete, non-generic wrapper instead",
                    source_file=func.source_file)
            for p in func.parameters:
                if not self._export_fn_type_ok(p.type, is_return=False):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`@export` function `{func.name}`: parameter `{p.name}` "
                        f"has type {self._describe_type_for_export(p.type)}, "
                        f"which is not C-ABI-safe",
                        func.line, func.column,
                        hint="exported signatures allow fixed-width integers, "
                             "Int/UInt, Float, and UnsafePointer<T>; pass an "
                             "aggregate by `UnsafePointer<S>`",
                        source_file=func.source_file)
            if not self._export_fn_type_ok(func.return_type, is_return=True):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`@export` function `{func.name}`: return type "
                    f"{self._describe_type_for_export(func.return_type)} is not "
                    f"C-ABI-safe",
                    func.line, func.column,
                    hint="exported returns allow fixed-width integers, Int/UInt, "
                         "Float, UnsafePointer<T>, Void, or Never (noreturn)",
                    source_file=func.source_file)
            self._register_export_symbol(sym, func)

        for static in getattr(program, 'statics', []):
            sec = section_name(static)
            if sec is not None and sec.strip() == "":
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    "`@section` name must be a non-empty string",
                    static.line, static.column, source_file=static.source_file)
            if not is_exported(static):
                continue
            sym = export_symbol(static)
            if not self._export_static_type_ok(static.type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`@export` static `{static.name}`: type "
                    f"{self._describe_type_for_export(static.type)} is not a "
                    f"C-ABI-safe data layout",
                    static.line, static.column,
                    hint="exported statics allow fixed-width integers, Int/UInt, "
                         "Float, arrays thereof, and structs of such fields",
                    source_file=static.source_file)
            self._register_export_symbol(sym, static)

    def check_module(
        self,
        module_ast: Program,
        module_path: Tuple[str, ...],
        checked_modules: Dict[Tuple[str, ...], Tuple[Program, 'Namespace']],
        builtin_namespace: 'Namespace',
        parent_namespace: Optional['Namespace'] = None,
        is_entry: bool = False
    ) -> Optional['Namespace']:
        """
        Type check a single module with its own namespace.

        This implements per-module type checking where each module is type-checked
        in isolation with only its imports visible. This is the Phase 5.0 approach.

        Args:
            module_ast: The parsed Program AST for this module
            module_path: The module's path as a tuple (e.g., ("std", "io"))
            checked_modules: Dict of already type-checked modules (path -> (ast, namespace))
            builtin_namespace: Pre-populated namespace with builtins
            parent_namespace: Optional parent module's namespace for nested modules
            is_entry: True if this is the entry module (should check for main)

        Returns:
            The module's namespace if successful, None on error
        """
        from namespace import (
            Namespace, FunctionSymbol, StructSymbol, EnumSymbol,
            TraitSymbol, TypeAliasSymbol, TraitMethodSymbol
        )
        from ast_nodes import Visibility

        # Create a fresh namespace for this module
        ns = Namespace(module_path=module_path)
        ns.package_root = builtin_namespace.package_root

        # Clone builtins into this module's namespace (all directly accessible)
        ns.merge_into(builtin_namespace)
        ns.directly_accessible = set(builtin_namespace.directly_accessible)

        # Inherit from parent if this is a nested module
        if parent_namespace:
            for name, sym in parent_namespace.structs.items():
                if sym.visibility == Visibility.PUBLIC:
                    if name not in ns.structs:
                        ns.register_struct(name, sym)
                    ns.make_accessible(name)
            for name, sym in parent_namespace.enums.items():
                if sym.visibility == Visibility.PUBLIC:
                    if name not in ns.enums:
                        ns.register_enum(name, sym)
                    ns.make_accessible(name)
            for name, sym in parent_namespace.functions.items():
                if sym.visibility == Visibility.PUBLIC:
                    if name not in ns.functions:
                        ns.register_function(name, sym)
                    ns.make_accessible(name)
            for name, sym in parent_namespace.traits.items():
                if sym.visibility == Visibility.PUBLIC:
                    if name not in ns.traits:
                        ns.register_trait(name, sym)
                    ns.make_accessible(name)

        # When an import copies a public struct/enum symbol into THIS namespace
        # (glob `import foo.*` or specific `import foo.{A}`), carry its trait
        # conformances along too. Without this, a containment/conformance query
        # in the importing module (e.g. "does DepList implement NoCopy?") sees the
        # copied struct but not its NoCopy conformance and wrongly errors — the
        # glob path does not register the source module in `ns.modules`, so
        # `type_conforms_to`'s cross-module walk cannot reach it either.
        def _import_conformances(dst_name, src_name, src_ns):
            src_map = src_ns.conformances.get(src_name)
            if not src_map:
                return
            dst_map = ns.conformances.setdefault(dst_name, {})
            for trait_name, assoc in src_map.items():
                dst_map.setdefault(trait_name, assoc)

        # Process imports - register imported modules in this namespace
        for imp in getattr(module_ast, 'imports', []):
            imp_path = tuple(imp.path)
            # Handle package/parent prefixes
            if imp_path and imp_path[0] == 'package':
                imp_path = imp_path[1:]
            elif imp_path and imp_path[0] == 'parent':
                # Resolve relative to current module
                if len(module_path) > 0:
                    imp_path = module_path[:-1] + imp_path[1:]
                else:
                    imp_path = imp_path[1:]

            if imp.is_glob:
                # import foo.* -> copy all public symbols to local namespace
                base_path = imp_path[:-1] if imp_path and imp_path[-1] == '*' else imp_path
                if base_path in checked_modules:
                    source_ast, source_ns = checked_modules[base_path]
                    for name, sym in source_ns.structs.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.structs:
                                ns.register_struct(name, sym)
                            ns.make_accessible(name)
                            _import_conformances(name, name, source_ns)
                    for name, sym in source_ns.enums.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.enums:
                                ns.register_enum(name, sym)
                            ns.make_accessible(name)
                            _import_conformances(name, name, source_ns)
                    for name, sym in source_ns.functions.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.functions:
                                ns.register_function(name, sym)
                            ns.make_accessible(name)
                    for name, sym in source_ns.traits.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.traits:
                                ns.register_trait(name, sym)
                            ns.make_accessible(name)
                    for name, sym in source_ns.statics.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.statics:
                                ns.register_static(name, sym)
                            ns.make_accessible(name)
            elif imp.symbols:
                # import foo.{A, B} -> copy specific symbols to local namespace
                if imp_path in checked_modules:
                    _, source_ns = checked_modules[imp_path]
                    aliases = imp.symbol_aliases or {}
                    for sym_name in imp.symbols:
                        # design 53: a `Name as Local` import binds the symbol
                        # under `Local` in this namespace — a pure local rename
                        # (the symbol object, and thus its mangling, is unchanged).
                        local = aliases.get(sym_name, sym_name)
                        # Copy the symbol from source to local namespace
                        if sym_name in source_ns.structs:
                            sym = source_ns.structs[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                if local not in ns.structs:
                                    ns.register_struct(local, sym)
                                ns.make_accessible(local)
                                _import_conformances(local, sym_name, source_ns)
                        elif sym_name in source_ns.enums:
                            sym = source_ns.enums[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                if local not in ns.enums:
                                    ns.register_enum(local, sym)
                                ns.make_accessible(local)
                                _import_conformances(local, sym_name, source_ns)
                        elif sym_name in source_ns.functions:
                            sym = source_ns.functions[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                # For an ALIASED function, bind a copy whose
                                # codegen name is the real symbol (design 53), so
                                # a call under the alias reaches the real
                                # definition. Unaliased imports are unchanged.
                                if local != sym_name and not sym.mangled_name:
                                    import dataclasses
                                    sym = dataclasses.replace(
                                        sym, mangled_name=sym_name)
                                if local not in ns.functions:
                                    ns.register_function(local, sym)
                                ns.make_accessible(local)
                        elif sym_name in source_ns.statics:
                            sym = source_ns.statics[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                if local not in ns.statics:
                                    ns.register_static(local, sym)
                                ns.make_accessible(local)
                        elif sym_name in source_ns.traits:
                            sym = source_ns.traits[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                if local not in ns.traits:
                                    ns.register_trait(local, sym)
                                ns.make_accessible(local)
                    # Also register module for qualified access to non-imported symbols
                    alias = imp.path[-1] if imp.path else ""
                    from namespace import ModuleSymbol
                    ns.modules[alias] = ModuleSymbol(
                        namespace=source_ns,
                        path=list(imp_path),
                        visibility=Visibility.PRIVATE
                    )
            else:
                # import foo.bar -> register module for qualified access
                if imp_path in checked_modules:
                    alias = imp.alias or (imp.path[-1] if imp.path else "")
                    _, source_ns = checked_modules[imp_path]
                    from namespace import ModuleSymbol
                    ns.modules[alias] = ModuleSymbol(
                        namespace=source_ns,
                        path=list(imp_path),
                        visibility=Visibility.PRIVATE  # Imports are private
                    )

        # Handle external module declarations (`module foo`)
        # These are registered for qualified access just like imports
        for mod_decl in getattr(module_ast, 'module_decls', []):
            if not mod_decl.is_inline:
                # External module declaration
                mod_path = (mod_decl.name,)
                if mod_path in checked_modules:
                    _, source_ns = checked_modules[mod_path]
                    from namespace import ModuleSymbol
                    mod_visibility = Visibility.PUBLIC if mod_decl.is_public else Visibility.PRIVATE
                    ns.modules[mod_decl.name] = ModuleSymbol(
                        namespace=source_ns,
                        path=list(mod_path),
                        visibility=mod_visibility
                    )

        # Register this module's own declarations

        # Save old state
        old_namespace = self.namespace
        old_module_path = self.current_module_path
        self.namespace = ns
        self.current_module_path = module_path

        # Validate: exports are only allowed in init.saw files (same rule as the
        # single-file path; enforced here so the unified pipeline still catches
        # a stray `export` in a regular entry/module file).
        self._validate_exports(module_ast)

        # Register type definitions
        for type_def in module_ast.type_definitions:
            self._register_type_definition(type_def)
            ns.make_accessible(type_def.name)

        # Register structs
        for struct in module_ast.structs:
            self._register_struct(struct)
            ns.make_accessible(struct.name)

        # Register enums
        for enum in module_ast.enums:
            self._register_enum(enum)
            ns.make_accessible(enum.name)

        # Register traits
        for trait in module_ast.traits:
            self._register_trait(trait)
            ns.make_accessible(trait.name)

        # Register extensions
        for extension in module_ast.extensions:
            self._register_extension(extension)

        # Validate `any Trait` existentials in declared signatures (design 51).
        self._validate_existentials_in_program(module_ast)

        # Check resource containment rules
        self._check_no_copy_containment()
        self._check_implicit_copy_containment()
        self._check_explicit_copy_containment()
        self._check_copy_trait_exclusivity()
        self._check_derivable_copy()
        self._check_derivable_equals()
        self._check_derivable_compare()
        self._check_derivable_hash()
        self._check_ord_hash_require_equatable()
        self._check_deinit_containment()

        # Register extern functions
        for extern_block in module_ast.extern_blocks:
            for extern_func in extern_block.functions:
                self._register_extern_function(extern_func)
                ns.make_accessible(extern_func.name)

        # Register functions
        for func in module_ast.functions:
            self._register_function(func)
            ns.make_accessible(func.name)

        # Register module-level statics (design 41). Accessible module-locally;
        # a `public` static is additionally visible to importers.
        for static in getattr(module_ast, 'statics', []):
            self._register_static(static)
            ns.make_accessible(static.name)

        # Handle inline module declarations BEFORE type-checking function bodies
        # This ensures that inline modules are available for use in the current module
        for mod_decl in getattr(module_ast, 'module_decls', []):
            if mod_decl.is_inline and mod_decl.body:
                inline_path = module_path + (mod_decl.name,)
                inline_ns = self.check_module(
                    mod_decl.body,
                    inline_path,
                    checked_modules,
                    builtin_namespace,
                    parent_namespace=ns,
                    is_entry=False
                )
                if inline_ns is None:
                    # Error in inline module
                    self.namespace = old_namespace
                    self.current_module_path = old_module_path
                    return None

                # Register the inline module in this module's namespace
                from namespace import ModuleSymbol
                mod_visibility = Visibility.PUBLIC if mod_decl.is_public else Visibility.PRIVATE
                ns.modules[mod_decl.name] = ModuleSymbol(
                    namespace=inline_ns,
                    path=list(inline_path),
                    visibility=mod_visibility
                )

        # Overloading (design 55): stamp overload-set codegen symbols for this
        # module now that all its signatures are registered.
        self._stamp_overload_symbols()

        # design 58: validate @export / @section on this module's functions and
        # statics. The export-symbol table accumulates across every module the
        # shared checker visits, so a duplicate exported C symbol across modules
        # in the same compilation unit is caught.
        self._check_attribute_semantics(module_ast)

        # Check for main function (only for entry module)
        if is_entry and not self.namespace.has_function("main"):
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                "no `main` function found",
                1, 1,
                hint="add a `func main() { }` function as the entry point, or use -c to compile as object file"
            )

        # Enable import checking for this module
        ns.enable_import_checking()

        # design 70 (A5): snapshot pristine (pre-body-check) copies of every
        # generic function template, so a suspending instantiation can be cloned +
        # substituted + re-checked for per-instantiation effect inference.
        import copy as _copy
        for func in module_ast.functions:
            if getattr(func, 'type_params', None) and not getattr(
                    func, 'is_mono_instance', False):
                self._pristine_generics[func.name] = _copy.deepcopy(func)
        # Method-level generic methods on a NON-generic extension: pristine snapshot
        # keyed by (struct, method), with the owning extension (design 70).
        for ext in module_ast.extensions:
            if getattr(ext, 'type_params', None):
                # design 74 (A5-rest, shape 2): an extension on a GENERIC struct
                # (`extension Holder<T>`). Snapshot every method (not just
                # method-level generics): driving `__drive(b.run())` for a concrete
                # receiver `Holder<Int>` monomorphizes the method over the STRUCT's
                # type params so the coroutine frame's `__recv` gets a concrete
                # layout. Keyed by (struct, method); the ext carries the struct's
                # type params for substitution.
                for m in ext.methods:
                    if not getattr(m, 'is_mono_instance', False):
                        self._pristine_generic_struct_methods[
                            (ext.struct_name, m.name)] = (_copy.deepcopy(m), ext)
                continue
            for m in ext.methods:
                if getattr(m, 'type_params', None) and not getattr(
                        m, 'is_mono_instance', False):
                    self._pristine_generic_methods[(ext.struct_name, m.name)] = (
                        _copy.deepcopy(m), ext)

        # Type check function bodies
        for func in module_ast.functions:
            self._check_function(func)

        # Type check method bodies
        for extension in module_ast.extensions:
            self._check_extension(extension)

        # design 70 (A5): build + re-check every queued generic instantiation so
        # its effect node (keyed by the mangled symbol) is populated before the
        # whole-program fixpoint. Splices concrete clones into `module_ast`, which
        # the coroutine transform and codegen then treat as ordinary functions.
        if is_entry:
            self._process_effect_monos(module_ast)
            # design 74 (A5-rest, shape 3): stash the entry module namespace so the
            # coroutine transform can splice + re-check a nested-generic
            # instantiation post-fixpoint with the SAME symbol scope the body checks
            # used (the namespace is restored below before the transform runs).
            self._entry_module_ns = ns
            self._entry_module_path = self.current_module_path

        # design 53: walk top-level static_assert conditions so their annotations
        # (Int.max limit tag, sizeof type args) are stamped for codegen.
        for sa in getattr(module_ast, 'static_asserts', []):
            self._check_static_assert(sa)

        # Restore old state
        self.namespace = old_namespace
        self.current_module_path = old_module_path

        # Whole-program `sync` effect analysis (design 22). The entry module is
        # checked last, after every other module's bodies have contributed their
        # call-graph edges, so this runs once over the complete graph.
        if is_entry:
            self.finalize_effects()

        if self.reporter.has_errors():
            return None

        return ns
