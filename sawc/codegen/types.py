"""
Type conversion utilities for the Saw code generator.

This module provides mixin methods for converting Saw types to LLVM IR types,
resolving type aliases, and type name mangling for generics.

Usage:
    class CodeGenerator(TypesMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import SawType, TypeKind
from type_identity import declaration_base, is_layout_transparent


class TypesMixin:
    """Mixin providing type conversion methods for CodeGenerator.

    Methods:
        _get_llvm_type: Convert SawType to LLVM IR type
        _resolve_type_alias: Resolve type aliases in a SawType
        _estimate_type_size: Estimate size of an LLVM type in bytes

    Name mangling lives in the single canonical module codegen/mangle.py.
    """

    def _lower_declared_return(self, saw_return_type):
        """The LLVM return type a declaration lowers to, plus whether it is the
        `-> Never` shape. Returns `(llvm_type, is_never)`.

        A `-> Never` declaration lowers to `void` + the `noreturn` attribute
        (the `_start`/`abort` C shape), because a function that does not
        return has no result to describe. `_get_llvm_type` maps `Never` to an
        i8 placeholder instead, which is right for an incidental type query and
        wrong for a signature: the caller would read an i8 result out of a call
        that produced nothing, and `_terminate_after_noreturn` (which asks the
        `noreturn` attribute) could never fire on it (design 228).

        Entry points (every site that turns a declared Saw return type into an
        LLVM one):
          `_lower_declared_return_of` -- `func` and extension-method declarations
          `_declare_extern_function` (core.py) -- `extern "C"`
          `_extern_llvm_type` (core.py) -- an extern's prototype type
          `_trait_slot_fn_type` (existentials.py) -- the vtable slot type, also the thunk's

        Not a function type (`_get_llvm_type`'s FUNCTION arm, and the closure
        body `_generate_closure` emits to match it). A type is a
        representation, not a declaration: a place-window closure can get
        `Never` as an ordinary substituted result, and the two halves of that
        representation are computed in different places from
        differently-substituted types, so lowering it to `void` would make them
        disagree. A diverging closure keeps the i8 placeholder; its callers
        still terminate, because the closure-call site asks
        `_terminate_after_noreturn` with the call expression instead.

        A `None` return type (a trait method with none recorded) is `void`.
        """
        if saw_return_type is None:
            return ir.VoidType(), False
        if saw_return_type.kind == TypeKind.NEVER:
            return ir.VoidType(), True
        return self._get_llvm_type(saw_return_type), False

    def _lower_declared_return_of(self, decl):
        """`_lower_declared_return`, asked about a DECLARATION rather than a type.

        The one thing a type cannot answer: whether its `Never` was written.
        The noreturn rule is about the declaration ("this function does not
        return"), and a `Never` that arrives by substitution is an ordinary
        value type, as `Void` is (design 132). A place accessor is the case: a
        window closure's result `__R` is `Never` whenever the window body never
        falls through, so `Slot<ArcE>.value<Never>` is a real function that
        returns a value nobody reads. The declaration pass is handed the
        substituted clone, so the clone carries the answer
        (`mono_substituted_never`) and this is where it is read.

        Entry points:
          `_declare_function` (core.py)
          `_declare_extension_methods` (core.py)
        """
        saw_return_type = getattr(decl, 'return_type', None)
        if getattr(decl, 'mono_substituted_never', False):
            return self._get_llvm_type(saw_return_type), False
        return self._lower_declared_return(saw_return_type)

    def _init_llvm_return_type(self, method, struct_llvm_type,
                               type_mapping=None):
        """The LLVM return type of an `init`.

        An `init` returns its receiver, or `Result<Receiver, E>` when it is the
        fallible form; the typechecker's `_init_declared_return` has already
        refused everything else, so this only has to tell the two apart. A
        `type_mapping`, when given, is applied first so a
        `Result<Holder<T>, E>` lowers at the instantiation.

        Entry points (the sites that build an `init`'s prototype):
          `_declare_extension_methods` (core.py)
        The body sites read `llvm_func.function_type.return_type` instead, so
        they follow whatever this decided with nothing to keep in step.
        """
        declared = getattr(method, 'return_type', None)
        if declared is None or not declared.is_result():
            return struct_llvm_type
        if type_mapping:
            declared = self._substitute_saw_type(declared, type_mapping)
        return self._get_llvm_type(declared)

    @staticmethod
    def _mark_noreturn(llvm_func, is_never: bool):
        """Attach `noreturn` when the declaration is the `-> Never` shape. The
        attribute is what every call site's `_terminate_after_noreturn` reads,
        so it travels with `_lower_declared_return`'s second answer."""
        if is_never:
            llvm_func.attributes.add("noreturn")

    def _get_llvm_type(self, saw_type: SawType) -> ir.Type:
        """Convert a SawType to the corresponding LLVM IR type.

        Handles all Saw types including:
        - Primitives: Int, Float, Bool, String
        - Fixed-width integers: Int8, Int16, Int32, Int64, UInt8, etc.
        - Compound types: Tuple, Array, Struct, Enum
        - Special types: Optional, Pointer, Function (closures), Self
        - Generic type parameters
        """
        if saw_type.kind == TypeKind.INT:
            return self.int_type  # design 47: platform-width (pointer-width)
        elif saw_type.kind == TypeKind.UINT:
            return self.int_type  # design 47: platform-width unsigned
        elif saw_type.kind == TypeKind.FLOAT:
            return ir.DoubleType()
        elif saw_type.kind == TypeKind.BOOL:
            return ir.IntType(1)
        elif saw_type.kind == TypeKind.NEVER:
            # Bottom type: a diverging `panic(...)` produces no value.
            # A concrete LLVM type is never actually needed (codegen terminates
            # the block with `unreachable`), but map it to i8 as a harmless
            # placeholder so any incidental type query does not crash.
            return ir.IntType(8)
        elif saw_type.kind == TypeKind.STRING:
            return ir.PointerType(ir.IntType(8))
        # Fixed-width integers
        elif saw_type.kind == TypeKind.INT8:
            return ir.IntType(8)
        elif saw_type.kind == TypeKind.INT16:
            return ir.IntType(16)
        elif saw_type.kind == TypeKind.INT32:
            return ir.IntType(32)
        elif saw_type.kind == TypeKind.INT64:
            return ir.IntType(64)
        elif saw_type.kind == TypeKind.UINT8:
            return ir.IntType(8)
        elif saw_type.kind == TypeKind.UINT16:
            return ir.IntType(16)
        elif saw_type.kind == TypeKind.UINT32:
            return ir.IntType(32)
        elif saw_type.kind == TypeKind.UINT64:
            return ir.IntType(64)
        elif saw_type.kind == TypeKind.POINTER:
            # Raw pointer type: UnsafePointer<T> or UnsafeConstPointer<T>
            if saw_type.inner_type is None:
                raise ValueError("Pointer type missing inner type")
            pointee_type = self._get_llvm_type(saw_type.inner_type)
            # `UnsafePointer<Void>` behaves like C `void*`: LLVM forbids a
            # pointer to `void`, so model it as `i8*` (byte-addressed). The
            # pointee may reach `void` only after type-param substitution
            # (T -> Void), so check the resolved LLVM type. Arises for a
            # Void-result Task control block.
            if isinstance(pointee_type, ir.VoidType):
                return ir.IntType(8).as_pointer()
            return ir.PointerType(pointee_type)
        elif saw_type.kind == TypeKind.EXISTENTIAL:
            # `any Trait` (design 51): a fat pointer { data ptr, vtable ptr }.
            return self._existential_llvm_type()
        elif saw_type.kind == TypeKind.REFERENCE:
            # Reference type: &T or &var T - compiled as pointer
            if saw_type.inner_type is None:
                raise ValueError("Reference type missing inner type")
            # `&any Trait` (design 51): the reference is the fat pointer (data,
            # vtable), a two-word value, not a thin pointer-to-fat-pointer.
            if saw_type.inner_type.kind == TypeKind.EXISTENTIAL:
                return self._existential_llvm_type()
            pointee_type = self._get_llvm_type(saw_type.inner_type)
            return ir.PointerType(pointee_type)
        elif saw_type.kind == TypeKind.VOID:
            return ir.VoidType()
        elif saw_type.kind == TypeKind.TUPLE:
            # Tuples are represented as LLVM structs
            if saw_type.element_types is None:
                return ir.LiteralStructType([])
            element_llvm_types = [self._get_llvm_type(t) for t in saw_type.element_types]
            return ir.LiteralStructType(element_llvm_types)
        elif saw_type.kind == TypeKind.STRUCT:
            # Look up the struct type (might actually be an enum, type param, or type alias)
            if saw_type.struct_name is None:
                raise ValueError("Struct type missing name")
            # `Box<any Trait, A>` (design 51): an owned erased value is itself a
            # fat pointer { heap data ptr, vtable ptr }. It never monomorphizes
            # through box.saw (its payload is unsized; construction, dispatch
            # and teardown are all special-cased), so intercept the type before
            # that path.
            if (saw_type.struct_name == "Box" and saw_type.type_args
                    and saw_type.type_args[0].kind == TypeKind.EXISTENTIAL):
                return self._existential_llvm_type()
            # UnsafeMemory<T, Use> is one word: the raw address. Its `T`/`Use`
            # are phantom (the declared `{ addr: Int }` body is never
            # materialized); every access is intercepted, so the value that
            # flows through codegen is just the pointer-width address (a fixed
            # MMIO address like 0x18003000 is a 32-bit value under a riscv32
            # target) (design 46).
            if saw_type.struct_name == "UnsafeMemory":
                return self.int_type
            # `FuncPointer<F>` is one word: the address of code whose signature
            # is `F`. It lowers to `F`'s own bare function pointer, the closure
            # lowering below minus the environment: no `env_ptr` parameter, no
            # `dtor_ptr` beside it. That makes it exactly a C function pointer
            # at the ABI and the indirect call a plain `call`. The declared
            # `{ addr: Int }` body is never materialized: every construction,
            # every call and `from_raw` are intercepted (design 226).
            if saw_type.struct_name == "FuncPointer":
                return self._funcpointer_llvm_type(saw_type)
            # The layout-transparent wrappers, through the shared predicate:
            # the `ReadOnly<T>`/`WriteOnly<T>` MMIO markers (a
            # `ReadOnly<UInt32>` field occupies exactly a `UInt32`, which is
            # what makes projection offsets land on the real register) and
            # `UnsafeMutableInterior<T>` (an inline `T`, so a cell field costs
            # no wrapper and `ptr()` is the address of the field itself, which
            # lets `Atomic<T>`/`SpinLock<T>` carry a real cell at the layout of
            # a bare `T`).
            if (is_layout_transparent(saw_type.struct_name)
                    and saw_type.type_args):
                return self._get_llvm_type(saw_type.type_args[0])
            # Check if it's a type alias (use namespace)
            alias_sym = self.namespace.lookup_type_alias(saw_type.struct_name)
            if alias_sym and alias_sym.aliased_type:
                return self._get_llvm_type(alias_sym.aliased_type)
            # Check if it's a type parameter in the current context
            if saw_type.struct_name in self.type_param_context:
                bound = self.type_param_context[saw_type.struct_name]
                # A self-mapping binding (`T -> T`) means an unsubstituted type
                # parameter reached codegen: recursing on it never terminates and
                # surfaces as `maximum recursion depth exceeded`, which fails the
                # whole compilation unit rather than the one construct at fault.
                # Stop at a bounded, named failure instead; every caller that
                # monomorphizes is expected to substitute first.
                if (bound is not None and bound.kind == TypeKind.STRUCT
                        and bound.struct_name == saw_type.struct_name):
                    raise ValueError(
                        f"type parameter `{saw_type.struct_name}` reached codegen "
                        f"unsubstituted (it is bound to itself); the call site "
                        f"must substitute against the monomorphization context "
                        f"before monomorphizing")
                return self._get_llvm_type(bound)
            # Check if it's actually an enum
            if saw_type.struct_name in self.enum_types:
                return self.enum_types[saw_type.struct_name][0]  # Return LLVM type
            # Handle generic struct with type arguments (e.g., VectorIterator<Int>)
            if saw_type.type_args:
                # Substitute any type parameters in the args against the current
                # monomorphization context before monomorphizing the nested
                # generic. Inside `unbox<Int>`, a parameter typed `Box<T>` must
                # monomorphize `Box<Int>` (context T->Int), not re-enter `Box<T>`
                # abstractly: with raw `[T]` args, `_ensure_monomorphized_struct`
                # zips Box's formal `T` against the arg `T`, self-maps `T->T`, and
                # generating field type `T` loops forever between the type-param
                # lookup here and the field-type walk. This covers every
                # nested-generic param/return/field type.
                concrete_args = [self._substitute_saw_type(a, self.type_param_context)
                                 for a in saw_type.type_args]
                # Check if this is actually a generic enum (like Result<T, E>)
                if saw_type.struct_name in self.generic_enums:
                    mangled_name = self._ensure_monomorphized_enum(saw_type.struct_name, concrete_args)
                    return self.enum_types[mangled_name][0]
                mangled_name = self._ensure_monomorphized_struct(saw_type.struct_name, concrete_args)
                return self.struct_types[mangled_name][0]
            if saw_type.struct_name not in self.struct_types:
                # A generic named with no arguments at all. That is well-formed
                # exactly when every parameter is defaulted (including a const
                # one): `Tag()` where `struct Tag<T = Int>`. Fill and
                # monomorphize, the same identity rule as every other
                # reference site (design 37).
                filled = self._fill_default_type_args(saw_type.struct_name, [])
                if filled:
                    if saw_type.struct_name in self.generic_enums:
                        mangled_name = self._ensure_monomorphized_enum(
                            saw_type.struct_name, filled)
                        return self.enum_types[mangled_name][0]
                    mangled_name = self._ensure_monomorphized_struct(
                        saw_type.struct_name, filled)
                    return self.struct_types[mangled_name][0]
                # A declaration this unit owns that the registration loop has
                # not reached. Register it here and ask again: the retry finds
                # a published handle, because registration publishes before it
                # lowers. Covers an enum spelled with the generic STRUCT kind
                # too, which is how a bare name arrives from a field or a
                # payload (design 246).
                if self._demand_register_type(saw_type.struct_name):
                    return self._get_llvm_type(saw_type)
                raise ValueError(f"Undefined struct: {saw_type.struct_name}")
            return self.struct_types[saw_type.struct_name][0]  # Return LLVM type
        elif saw_type.kind == TypeKind.OPTIONAL:
            # Optionals are represented as { i1, T } where i1 indicates presence
            if saw_type.inner_type is None:
                # None literal with unknown type - platform Int placeholder
                inner_llvm_type = self.int_type
            elif saw_type.inner_type.kind == TypeKind.VOID:
                # `Void?` (e.g. an optional-chain assignment result): LLVM has no
                # void-in-struct, so the unit payload is a placeholder i8. Only the
                # is_some flag is ever inspected.
                inner_llvm_type = ir.IntType(8)
            else:
                inner_llvm_type = self._get_llvm_type(saw_type.inner_type)
            return ir.LiteralStructType([ir.IntType(1), inner_llvm_type])
        elif saw_type.kind == TypeKind.ENUM:
            # Look up the enum type
            if saw_type.enum_name is None:
                raise ValueError("Enum type missing name")
            # Handle generic enum with type_args
            if saw_type.type_args:
                # Substitute type params against the current context first, as
                # the STRUCT branch above does, so `Maybe<T>`/`Result<T, E>` in a
                # param/return position specialize with concrete args rather
                # than recursing.
                concrete_args = [self._substitute_saw_type(a, self.type_param_context)
                                 for a in saw_type.type_args]
                mangled_name = self._ensure_monomorphized_enum(saw_type.enum_name, concrete_args)
                return self.enum_types[mangled_name][0]
            if saw_type.enum_name not in self.enum_types:
                # See the struct arm above.
                if self._demand_register_type(saw_type.enum_name):
                    return self._get_llvm_type(saw_type)
                raise ValueError(f"Undefined enum: {saw_type.enum_name}")
            return self.enum_types[saw_type.enum_name][0]  # Return LLVM type
        elif saw_type.kind == TypeKind.TYPE_PARAM:
            # Look up the type parameter in the current context
            if saw_type.type_param_name is None:
                raise ValueError("Type parameter missing name")
            if saw_type.type_param_name not in self.type_param_context:
                raise ValueError(f"Unbound type parameter: {saw_type.type_param_name}")
            return self._get_llvm_type(self.type_param_context[saw_type.type_param_name])
        elif saw_type.kind == TypeKind.ARRAY:
            # Arrays are LLVM array types [N x T]
            if saw_type.array_element_type is None:
                raise ValueError("Array type missing element type or size")
            size = saw_type.array_size
            if size is None:
                # A length that is still symbolic: `[Int; N]` on a const-generic
                # parameter (design 148). This instantiation's bindings supply
                # it, exactly as the TYPE_PARAM arm above resolves an element
                # type. Resolving at this chokepoint means every path that
                # reaches an LLVM type gets the length, not just the ones that
                # happened to run substitution first.
                size, _ = saw_type._substituted_length(
                    self._const_length_context())
            if size is None:
                # A declared length that did not fold earlier. Codegen, with its
                # full layout oracle, is the last position that can answer, so
                # the fold is tried here and its answer kept: a length written
                # inside a type argument (`sizeof<[UInt8; sizeof<Int>()]>()`)
                # is visited by no declared-type walk and first folds here.
                #
                # A length that still does not fold (`[UInt8; count]` naming a
                # runtime binding) is the author's mistake, not a compiler
                # invariant: report it where the length is written, with the
                # wording the repeat-count position uses (design 148).
                from .core import CodegenUserError
                from const_eval import (const_eval, ConstEvalError,
                                        CONST_LENGTH_HINT)
                expr = saw_type.array_size_expr
                what, line, column = "the length", 0, 0
                if expr is not None:
                    line = expr.line or 0
                    column = expr.column or 0
                    try:
                        folded = const_eval(expr, env=self._const_param_env(),
                                            metric=self._const_type_metric,
                                            width=self.int_width)
                        if isinstance(folded, int) and \
                                not isinstance(folded, bool):
                            size = folded
                    except ConstEvalError as e:
                        what = e.what
                        line = e.line or line
                        column = e.column or column
                if size is None:
                    raise CodegenUserError(
                        f"array length is not a compile-time constant: {what} "
                        f"is not allowed here", line, column,
                        hint=CONST_LENGTH_HINT,
                        source_file=getattr(expr, 'source_file', None))
            if size < 0:
                # A length that folded to a negative number (`[UInt8; -1]`,
                # `[UInt8; 2 - 3]`) would reach llvmlite as `[-1 x i8]`; report
                # it as the user error it is, as the repeat count does.
                from .core import CodegenUserError
                # A folded length arrives with its expression; a length that
                # was already a number when the type was built does not, so the
                # anchor has to tolerate its absence rather than turn a clean
                # diagnostic into a crash.
                expr = saw_type.array_size_expr
                raise CodegenUserError(
                    f"array length is negative (`{size}`)",
                    (expr.line if expr is not None else 0) or 0,
                    (expr.column if expr is not None else 0) or 0,
                    hint="an array length counts elements, so it starts at 0",
                    source_file=getattr(expr, 'source_file', None))
            elem_type = self._get_llvm_type(saw_type.array_element_type)
            return ir.ArrayType(elem_type, size)
        elif saw_type.kind == TypeKind.FUNCTION:
            # Closures are { fn_ptr, env_ptr, dtor_ptr } (design 71). fn_ptr takes
            # (env_ptr, params...) -> ret. dtor_ptr is `void (i8*)` — the env
            # destructor for an escaping closure that owns captures, or null for a
            # non-owning closure (no captures / borrow-only / non-escaping). The
            # closure value carries its own destructor so it can be dropped
            # correctly wherever it flows (bound, struct field, Vector, returned):
            # dropping = `if dtor: dtor(env)` (releases owned captures + frees the
            # heap env exactly once).
            param_types = [self._get_llvm_type(t) for t in (saw_type.param_types or [])]
            # The declared-return funnel deliberately does not reach here: a
            # function type is a representation, not a declaration; see
            # `_lower_declared_return`'s docstring for why `Never` stays the i8
            # placeholder in it.
            if saw_type.func_return_type and saw_type.func_return_type.kind != TypeKind.VOID:
                ret_type = self._get_llvm_type(saw_type.func_return_type)
            else:
                ret_type = ir.VoidType()
            # Function takes env_ptr (i8*) as first parameter
            env_ptr_type = ir.PointerType(ir.IntType(8))
            fn_type = ir.FunctionType(ret_type, [env_ptr_type] + param_types)
            fn_ptr_type = ir.PointerType(fn_type)
            dtor_ptr_type = ir.PointerType(ir.FunctionType(ir.VoidType(), [env_ptr_type]))
            # Closure struct: { fn_ptr, env_ptr, dtor_ptr }
            return ir.LiteralStructType([fn_ptr_type, env_ptr_type, dtor_ptr_type])
        elif saw_type.kind == TypeKind.SELF:
            # Self type - resolve to current struct context
            if self.self_type_context is None:
                raise ValueError("Self type used outside of extension context")
            # Special handling for primitive type extensions
            if (self.self_type_context not in self.struct_types
                    and self.self_type_context not in self.enum_types
                    and self._primitive_self_llvm_type(
                        self.self_type_context) is None):
                raise ValueError(f"Self type refers to undefined struct: {self.self_type_context}")
            # `-> Self` in an enum extension resolves to the enum's own LLVM
            # type, alongside the primitive and struct receivers.
            return self._ext_self_types(self.self_type_context)[0]
        else:
            raise ValueError(f"Unknown type: {saw_type}")

    def _funcpointer_signature(self, saw_type: SawType):
        """`F` out of a `FuncPointer<F>` SawType, substituted, or None.

        The one place codegen unwraps the type (design 226). Substituting
        against the active monomorphization context is what lets a
        `FuncPointer<F>` written inside a generic body reach a concrete
        signature — the same first step every other generic arm here takes.
        """
        if (saw_type is None or saw_type.kind != TypeKind.STRUCT
                or saw_type.struct_name != "FuncPointer"):
            return None
        args = saw_type.type_args or []
        if not args:
            return None
        f = self._substitute_saw_type(args[0], self.type_param_context)
        return f if f is not None and f.kind == TypeKind.FUNCTION else None

    def _funcpointer_llvm_fn_type(self, f: SawType) -> ir.FunctionType:
        """The bare LLVM function type of a `FuncPointer`'s signature `F`.

        The closure lowering with the environment removed: parameters exactly
        as written, no leading `env_ptr`. Read by the type lowering, by the
        coerced-literal emission (which defines a function of this type) and by
        the indirect call (which calls through one), so the three cannot drift.
        """
        param_types = [self._get_llvm_type(t) for t in (f.param_types or [])]
        if f.func_return_type and f.func_return_type.kind != TypeKind.VOID:
            ret_type = self._get_llvm_type(f.func_return_type)
        else:
            ret_type = ir.VoidType()
        return ir.FunctionType(ret_type, param_types)

    def _funcpointer_llvm_type(self, saw_type: SawType) -> ir.Type:
        """`FuncPointer<F>` as an LLVM type: a pointer to `F`'s bare function."""
        f = self._funcpointer_signature(saw_type)
        if f is None:
            raise ValueError(
                f"`FuncPointer` reached codegen without a function-type "
                f"argument: {saw_type}")
        return ir.PointerType(self._funcpointer_llvm_fn_type(f))

    def _resolve_type_alias(self, saw_type: SawType) -> SawType:
        """Resolve type aliases in a SawType.

        Recursively resolves type aliases for struct types, optionals,
        tuples, and enums with type arguments.
        """
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            # Use namespace for type alias lookup
            alias_sym = self.namespace.lookup_type_alias(saw_type.struct_name)
            if alias_sym and alias_sym.aliased_type:
                return alias_sym.aliased_type
            if saw_type.type_args:
                resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name, type_args=resolved_args)
        elif saw_type.kind == TypeKind.OPTIONAL and saw_type.inner_type:
            resolved_inner = self._resolve_type_alias(saw_type.inner_type)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        elif saw_type.kind == TypeKind.TUPLE and saw_type.element_types:
            resolved_elems = [self._resolve_type_alias(t) for t in saw_type.element_types]
            return SawType(TypeKind.TUPLE, element_types=resolved_elems)
        elif saw_type.kind == TypeKind.ENUM and saw_type.type_args:
            resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
            return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args)
        return saw_type

    def _estimate_type_size(self, llvm_type: ir.Type) -> int:
        """Estimate the size of an LLVM type in bytes (conservative estimate).

        Ignores alignment and assumes 64-bit pointers, so it is wrong for real
        layout; nothing outside its own recursion calls it.
        """
        if isinstance(llvm_type, ir.IntType):
            return (llvm_type.width + 7) // 8  # Round up to nearest byte
        elif isinstance(llvm_type, ir.DoubleType):
            return 8
        elif isinstance(llvm_type, ir.FloatType):
            return 4
        elif isinstance(llvm_type, ir.PointerType):
            return 8  # Assume 64-bit pointers
        elif isinstance(llvm_type, (ir.LiteralStructType, ir.IdentifiedStructType)):
            # Sum of element sizes
            return sum(self._estimate_type_size(elem) for elem in llvm_type.elements)
        elif isinstance(llvm_type, ir.ArrayType):
            return llvm_type.count * self._estimate_type_size(llvm_type.element)
        else:
            return 8  # Default conservative estimate
