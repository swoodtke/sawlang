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
        _type_to_string: Convert SawType to string for name mangling
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
            return ir.IntType(64)
        elif saw_type.kind == TypeKind.FLOAT:
            return ir.DoubleType()
        elif saw_type.kind == TypeKind.BOOL:
            return ir.IntType(1)
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
            # Check if it's a type alias (use namespace)
            alias_sym = self.namespace.lookup_type_alias(saw_type.struct_name)
            if alias_sym and alias_sym.aliased_type:
                return self._get_llvm_type(alias_sym.aliased_type)
            # Check if it's a type parameter in the current context
            if saw_type.struct_name in self.type_param_context:
                return self._get_llvm_type(self.type_param_context[saw_type.struct_name])
            # Check if it's actually an enum
            if saw_type.struct_name in self.enum_types:
                return self.enum_types[saw_type.struct_name][0]  # Return LLVM type
            # Handle generic struct with type arguments (e.g., VectorIterator<Int>)
            if saw_type.type_args:
                mangled_name = self._ensure_monomorphized_struct(saw_type.struct_name, saw_type.type_args)
                return self.struct_types[mangled_name][0]
            if saw_type.struct_name not in self.struct_types:
                raise ValueError(f"Undefined struct: {saw_type.struct_name}")
            return self.struct_types[saw_type.struct_name][0]  # Return LLVM type
        elif saw_type.kind == TypeKind.OPTIONAL:
            # Optionals are represented as { i1, T } where i1 indicates presence
            if saw_type.inner_type is None:
                # None literal with unknown type - use i64 as placeholder
                inner_llvm_type = ir.IntType(64)
            else:
                inner_llvm_type = self._get_llvm_type(saw_type.inner_type)
            return ir.LiteralStructType([ir.IntType(1), inner_llvm_type])
        elif saw_type.kind == TypeKind.ENUM:
            # Look up the enum type
            if saw_type.enum_name is None:
                raise ValueError("Enum type missing name")
            # Handle generic enum with type_args
            if saw_type.type_args:
                mangled_name = self._ensure_monomorphized_enum(saw_type.enum_name, saw_type.type_args)
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
            if saw_type.array_element_type is None or saw_type.array_size is None:
                raise ValueError("Array type missing element type or size")
            elem_type = self._get_llvm_type(saw_type.array_element_type)
            return ir.ArrayType(elem_type, saw_type.array_size)
        elif saw_type.kind == TypeKind.FUNCTION:
            # Closures are { fn_ptr, env_ptr } where fn_ptr takes (env_ptr, params...) -> ret
            param_types = [self._get_llvm_type(t) for t in (saw_type.param_types or [])]
            if saw_type.func_return_type and saw_type.func_return_type.kind != TypeKind.VOID:
                ret_type = self._get_llvm_type(saw_type.func_return_type)
            else:
                ret_type = ir.VoidType()
            # Function takes env_ptr (i8*) as first parameter
            env_ptr_type = ir.PointerType(ir.IntType(8))
            fn_type = ir.FunctionType(ret_type, [env_ptr_type] + param_types)
            fn_ptr_type = ir.PointerType(fn_type)
            # Closure struct: { fn_ptr, env_ptr }
            return ir.LiteralStructType([fn_ptr_type, env_ptr_type])
        elif saw_type.kind == TypeKind.SELF:
            # Self type - resolve to current struct context
            if self.self_type_context is None:
                raise ValueError("Self type used outside of extension context")
            # Special handling for primitive type extensions
            if self.self_type_context == "String":
                return ir.IntType(8).as_pointer()  # String is i8*
            if self.self_type_context not in self.struct_types:
                raise ValueError(f"Self type refers to undefined struct: {self.self_type_context}")
            return self.struct_types[self.self_type_context][0]
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

    def _type_to_string(self, saw_type: SawType) -> str:
        """Convert a SawType to a string representation for name mangling.

        Used to generate unique names for generic instantiations.
        For example: identity<Int> becomes identity$Int
        """
        if saw_type.kind == TypeKind.INT:
            return "Int"
        elif saw_type.kind == TypeKind.INT8:
            return "Int8"
        elif saw_type.kind == TypeKind.INT16:
            return "Int16"
        elif saw_type.kind == TypeKind.INT32:
            return "Int32"
        elif saw_type.kind == TypeKind.INT64:
            return "Int64"
        elif saw_type.kind == TypeKind.UINT8:
            return "UInt8"
        elif saw_type.kind == TypeKind.UINT16:
            return "UInt16"
        elif saw_type.kind == TypeKind.UINT32:
            return "UInt32"
        elif saw_type.kind == TypeKind.UINT64:
            return "UInt64"
        elif saw_type.kind == TypeKind.FLOAT:
            return "Float"
        elif saw_type.kind == TypeKind.BOOL:
            return "Bool"
        elif saw_type.kind == TypeKind.STRING:
            return "String"
        elif saw_type.kind == TypeKind.VOID:
            return "Void"
        elif saw_type.kind == TypeKind.POINTER:
            if saw_type.inner_type:
                return f"Ptr_{self._type_to_string(saw_type.inner_type)}"
            return "Ptr"
        elif saw_type.kind == TypeKind.TUPLE:
            if saw_type.element_types:
                inner = "_".join(self._type_to_string(t) for t in saw_type.element_types)
                return f"Tuple_{inner}"
            return "Tuple"
        elif saw_type.kind == TypeKind.STRUCT:
            return saw_type.struct_name
        elif saw_type.kind == TypeKind.OPTIONAL:
            if saw_type.inner_type:
                return f"Opt_{self._type_to_string(saw_type.inner_type)}"
            return "Opt"
        elif saw_type.kind == TypeKind.ENUM:
            return saw_type.enum_name
        else:
            return "Unknown"
