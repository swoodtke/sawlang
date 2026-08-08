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


class TypesMixin:
    """Mixin providing type conversion methods for CodeGenerator.

    Methods:
        _get_llvm_type: Convert SawType to LLVM IR type
        _resolve_type_alias: Resolve type aliases in a SawType
        _estimate_type_size: Estimate size of an LLVM type in bytes

    Name mangling lives in the single canonical module codegen/mangle.py.
    """

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
            # Bottom type (design 49): a diverging `panic(...)` produces no value.
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
            # Void-result Task control block (design 77 item 1).
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
            # `&any Trait` (design 51): the reference IS the fat pointer (data,
            # vtable) — a two-word value, not a thin pointer-to-fat-pointer.
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
            # `Box<any Trait, A>` (design 51): an OWNED erased value is itself a fat
            # pointer { heap data ptr, vtable ptr }. It never monomorphizes through
            # box.saw (its payload is unsized) — construction/dispatch/teardown are
            # all special-cased — so intercept the type before that path.
            if (saw_type.struct_name == "Box" and saw_type.type_args
                    and saw_type.type_args[0].kind == TypeKind.EXISTENTIAL):
                return self._existential_llvm_type()
            # design 46: UnsafeMemory<T, Use> is ONE WORD — the raw address.
            # Its `T`/`Use` are phantom (the declared `{ addr: Int }` body is
            # never materialized); every access is intercepted, so the value that
            # flows through codegen is just the pointer-width address (design 47:
            # addresses are pointer-width, so a fixed MMIO address like
            # 0x18003000 is a 32-bit value under a riscv32 target).
            if saw_type.struct_name == "UnsafeMemory":
                return self.int_type
            # design 46: ReadOnly<T> / WriteOnly<T> are LAYOUT-TRANSPARENT field
            # markers — a `ReadOnly<UInt32>` field occupies exactly a `UInt32`,
            # so it lowers to the inner type's layout (no wrapper struct). This is
            # what makes projection offsets land on the real register.
            if (saw_type.struct_name in ("ReadOnly", "WriteOnly")
                    and saw_type.type_args):
                return self._get_llvm_type(saw_type.type_args[0])
            # Check if it's a type alias (use namespace)
            alias_sym = self.namespace.lookup_type_alias(saw_type.struct_name)
            if alias_sym and alias_sym.aliased_type:
                return self._get_llvm_type(alias_sym.aliased_type)
            # Check if it's a type parameter in the current context
            if saw_type.struct_name in self.type_param_context:
                bound = self.type_param_context[saw_type.struct_name]
                # A SELF-MAPPING binding (`T -> T`) means an unsubstituted type
                # parameter reached codegen: recursing on it never terminates and
                # surfaces as `maximum recursion depth exceeded`, which fails the
                # WHOLE compilation unit rather than the one construct at fault
                # (DF-123a). Stop at a bounded, named failure instead — every
                # caller that monomorphizes is expected to substitute first.
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
                # monomorphization context BEFORE monomorphizing the nested
                # generic. Inside `unbox<Int>`, a parameter typed `Box<T>` must
                # monomorphize `Box<Int>` (context T->Int), NOT re-enter `Box<T>`
                # abstractly: with raw `[T]` args, `_ensure_monomorphized_struct`
                # zips Box's formal `T` against the arg `T`, self-maps `T->T`, and
                # generating field type `T` loops forever between the type-param
                # lookup here and the field-type walk. Substituting first is the
                # single shared fix for every nested-generic param/return/field
                # type (brief 36, L8).
                concrete_args = [self._substitute_saw_type(a, self.type_param_context)
                                 for a in saw_type.type_args]
                # Check if this is actually a generic enum (like Result<T, E>)
                if saw_type.struct_name in self.generic_enums:
                    mangled_name = self._ensure_monomorphized_enum(saw_type.struct_name, concrete_args)
                    return self.enum_types[mangled_name][0]
                mangled_name = self._ensure_monomorphized_struct(saw_type.struct_name, concrete_args)
                return self.struct_types[mangled_name][0]
            if saw_type.struct_name not in self.struct_types:
                # A GENERIC named with no arguments at all. That is well-formed
                # exactly when every parameter is defaulted (design 37, and
                # design 148 for a const one): `Tag()` where `struct Tag<T =
                # Int>`. Nothing had filled the defaults on this path, so a
                # zero-argument init on such a type reached here as a bare name
                # and raised an internal compiler error. Fill and monomorphize —
                # the same identity rule as every other reference site.
                filled = self._fill_default_type_args(saw_type.struct_name, [])
                if filled:
                    if saw_type.struct_name in self.generic_enums:
                        mangled_name = self._ensure_monomorphized_enum(
                            saw_type.struct_name, filled)
                        return self.enum_types[mangled_name][0]
                    mangled_name = self._ensure_monomorphized_struct(
                        saw_type.struct_name, filled)
                    return self.struct_types[mangled_name][0]
                raise ValueError(f"Undefined struct: {saw_type.struct_name}")
            return self.struct_types[saw_type.struct_name][0]  # Return LLVM type
        elif saw_type.kind == TypeKind.OPTIONAL:
            # Optionals are represented as { i1, T } where i1 indicates presence
            if saw_type.inner_type is None:
                # None literal with unknown type - platform Int placeholder
                inner_llvm_type = self.int_type
            elif saw_type.inner_type.kind == TypeKind.VOID:
                # `Void?` (design 111 optional-chain assignment result): LLVM has no
                # void-in-struct, so the unit payload is a placeholder i8. Only the
                # is_some flag is ever inspected (via `guard let _ =` / discard).
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
                # Substitute type params against the current context first — same
                # nested-generic monomorphization fix as the STRUCT branch above
                # (brief 36, L8), so `Maybe<T>`/`Result<T, E>` in a param/return
                # position specialize with concrete args rather than recursing.
                concrete_args = [self._substitute_saw_type(a, self.type_param_context)
                                 for a in saw_type.type_args]
                mangled_name = self._ensure_monomorphized_enum(saw_type.enum_name, concrete_args)
                return self.enum_types[mangled_name][0]
            if saw_type.enum_name not in self.enum_types:
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
                # A length that is still symbolic — `[Int; N]` on a const-generic
                # parameter (design 148). This instantiation's bindings supply
                # it, exactly as the TYPE_PARAM arm above resolves an element
                # type. Resolving at this chokepoint means every path that
                # reaches an LLVM type gets the length, not just the ones that
                # happened to run substitution first.
                size, _ = saw_type._substituted_length(self.type_param_context)
            if size is None:
                # A DECLARED length that never folded — `[UInt8; ARENA_BYTES]`
                # naming a module `static`, say. This is the position design 148
                # says owns the requirement ("a declared array length reaching
                # codegen reports it"), and it is the author's mistake, not a
                # compiler invariant: report it where the length is written,
                # with the same wording the repeat-count position already uses.
                # It raised a bare ValueError until design 172 part 2 hit it —
                # so one spelling of one rule gave a clean, hint-carrying error
                # and the other gave an internal compiler error (DF-172f).
                from .core import CodegenUserError
                from const_eval import const_eval, ConstEvalError
                expr = saw_type.array_size_expr
                what, line, column = "the length", 0, 0
                if expr is not None:
                    line = getattr(expr, 'line', 0) or 0
                    column = getattr(expr, 'column', 0) or 0
                    try:
                        const_eval(expr, env=self._const_param_env(),
                                   metric=self._const_type_metric,
                                   width=self.int_width)
                    except ConstEvalError as e:
                        what = e.what
                        line = e.line or line
                        column = e.column or column
                raise CodegenUserError(
                    f"array length is not a compile-time constant: {what} is "
                    f"not allowed here", line, column,
                    hint="a length is fixed at compile time — use a literal, a "
                         "const generic parameter, or arithmetic over them",
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
            # Design 145: `-> Self` in an ENUM extension resolves to the enum's
            # own LLVM type, alongside the primitive and struct receivers.
            return self._ext_self_types(self.self_type_context)[0]
        else:
            raise ValueError(f"Unknown type: {saw_type}")

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

        Used for calculating enum payload sizes. This is a simplified version
        that doesn't account for alignment - in production, use LLVM's DataLayout.
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
