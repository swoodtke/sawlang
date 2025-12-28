"""
Function and method call generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for function
calls, method calls, static method calls, and built-in functions like print
and sizeof.

Usage:
    class CodeGenerator(CallsMixin, ...):
        pass
"""

from typing import List
from llvmlite import ir
from ast_nodes import (
    FunctionCall, StructInit, Argument, SawType, TypeKind,
    MethodCall, MemberAccess, Identifier, SelfExpr, EnumInit
)


class CallsMixin:
    """Mixin providing function and method call generation methods for CodeGenerator.

    Methods:
        _generate_function_call: Generate code for function calls
        _generate_print: Generate code for the print built-in
        _generate_sizeof: Generate code for the sizeof built-in
        _generate_method_call: Generate code for method calls
        _generate_static_method_call: Generate code for static method calls
        _resolve_module_chain: Resolve module access chains
        _generate_module_function_call: Generate module function calls
        _generate_module_struct_init: Generate module struct initialization
        _get_member_pointer: Get pointer to struct field for mutable access
        _generate_self_expr: Generate code for 'self' keyword
        _generate_enum_init: Generate code for enum variant initialization
    """

    def _generate_function_call(self, expr: FunctionCall):
        """Generate code for a function call.

        Handles regular functions, generic functions, closures, struct
        initialization, and built-in functions.
        """
        # Handle built-in print function
        if expr.name == "print":
            return self._generate_print(expr.arguments)

        # Handle built-in sizeof<T>() function
        if expr.name == "sizeof":
            return self._generate_sizeof(expr)

        # Check if the name refers to a closure variable
        if expr.name in self.variables:
            closure_ptr = self.variables[expr.name]
            closure_val = self.builder.load(closure_ptr, name="closure")
            # Check if it's a closure struct (has fn_ptr and env_ptr fields)
            if isinstance(closure_val.type, ir.LiteralStructType) and len(closure_val.type.elements) == 2:
                # Call the closure
                fn_ptr = self.builder.extract_value(closure_val, 0, name="fn_ptr")
                env_ptr = self.builder.extract_value(closure_val, 1, name="env_ptr")
                arg_vals = [self._generate_expression(arg.value) for arg in expr.arguments]
                return self.builder.call(fn_ptr, [env_ptr] + arg_vals, name="closure_call")

        # Check if this is actually a struct init (parser treats empty parens as function call)
        if expr.name in self.generic_structs or expr.name in self.struct_types:
            # Convert to struct init and generate that instead
            field_inits = [(arg.name, arg.value) for arg in expr.arguments if arg.name]
            struct_init = StructInit(
                struct_name=expr.name,
                field_inits=field_inits,
                type_args=expr.type_args,
                line=expr.line,
                column=expr.column
            )
            # Copy resolved_init_params if it was set during typechecking
            if hasattr(expr, 'resolved_init_params'):
                struct_init.resolved_init_params = expr.resolved_init_params
            return self._generate_struct_init(struct_init)

        # Check if this is a call to a generic function
        if expr.name in self.generic_functions:
            if not expr.type_args:
                raise ValueError(
                    f"Generic function {expr.name} requires type arguments. "
                    f"Use {expr.name}<Type>(...)"
                )
            # Instantiate the generic function
            mangled_name = self._instantiate_generic_function(expr.name, expr.type_args)
            func = self.functions[mangled_name]
        else:
            # Look up regular user-defined function
            if expr.name not in self.functions:
                raise ValueError(f"Undefined function: {expr.name}")
            func = self.functions[expr.name]

        # Arguments are now Argument objects with .value
        args = [self._generate_expression(arg.value) for arg in expr.arguments]
        result = self.builder.call(func, args, name="calltmp")

        # Wrap result in optional for extern functions that return nullable pointers
        if expr.name in self.extern_optional_returns:
            inner_type = self.extern_optional_returns[expr.name]
            optional_type = self._get_llvm_type(SawType(TypeKind.OPTIONAL, inner_type=inner_type))
            # Check if pointer is NULL
            null_ptr = ir.Constant(result.type, None)
            is_not_null = self.builder.icmp_unsigned('!=', result, null_ptr, name="is_not_null")
            # Build optional struct: {i1 is_some, T value}
            opt_val = ir.Constant(optional_type, ir.Undefined)
            opt_val = self.builder.insert_value(opt_val, is_not_null, 0, name="opt_flag")
            opt_val = self.builder.insert_value(opt_val, result, 1, name="opt_val")
            return opt_val

        return result

    def _generate_print(self, arguments: List[Argument]):
        """Generate code for the print built-in function."""
        if not arguments:
            # Print newline
            fmt = self._create_string_constant("\n")
            zero = ir.Constant(ir.IntType(32), 0)
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            return self.builder.call(self.printf, [fmt_ptr])

        # Arguments are Argument objects with .value
        arg = arguments[0]
        value = self._generate_expression(arg.value)

        # Choose format based on type
        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
                # Bool - convert to string
                fmt = self._create_string_constant("%s\n")
                zero = ir.Constant(ir.IntType(32), 0)
                fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)

                # Create true/false strings
                true_str = self._create_string_constant("true")
                false_str = self._create_string_constant("false")
                true_ptr = self.builder.gep(true_str, [zero, zero], inbounds=True)
                false_ptr = self.builder.gep(false_str, [zero, zero], inbounds=True)

                str_ptr = self.builder.select(value, true_ptr, false_ptr)
                return self.builder.call(self.printf, [fmt_ptr, str_ptr])
            else:
                # Integer - extend to i64 for printf %lld format
                fmt = self._create_string_constant("%lld\n")
                zero = ir.Constant(ir.IntType(32), 0)
                fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
                # Extend smaller integers to i64 for printf
                if value.type.width < 64:
                    # Use zext for unsigned types, sext for signed types
                    saw_type = self._infer_saw_type(arg.value)
                    unsigned_kinds = {TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}
                    if saw_type and saw_type.kind in unsigned_kinds:
                        value = self.builder.zext(value, ir.IntType(64), name="print_ext")
                    else:
                        value = self.builder.sext(value, ir.IntType(64), name="print_ext")
                return self.builder.call(self.printf, [fmt_ptr, value])

        elif isinstance(value.type, ir.DoubleType):
            fmt = self._create_string_constant("%f\n")
            zero = ir.Constant(ir.IntType(32), 0)
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            return self.builder.call(self.printf, [fmt_ptr, value])

        elif isinstance(value.type, ir.PointerType):
            # String
            fmt = self._create_string_constant("%s\n")
            zero = ir.Constant(ir.IntType(32), 0)
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            return self.builder.call(self.printf, [fmt_ptr, value])

        else:
            raise ValueError(f"Cannot print type: {value.type}")

    def _generate_sizeof(self, expr: FunctionCall):
        """Generate code for sizeof<T>() - returns the size in bytes of type T."""
        # Get the type argument
        if not expr.type_args or len(expr.type_args) != 1:
            raise ValueError("sizeof requires exactly one type argument")

        saw_type = expr.type_args[0]
        # Resolve type parameters if in a generic context
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name in self.type_param_context:
            saw_type = self.type_param_context[saw_type.struct_name]
        llvm_type = self._get_llvm_type(saw_type)
        size = llvm_type.get_abi_size(self.target_data)
        return ir.Constant(ir.IntType(64), size)

    def _generate_method_call(self, expr: MethodCall):
        """Generate code for method call, static method call, enum initialization, or module function call.

        The parser creates MethodCall for all these cases:
        - object.method(args) - instance method call
        - StructName.method(args) - static method call
        - EnumType.Variant(args) - enum variant initialization
        - ModuleName.function(args) - module function call (Phase 2)
        """
        # Check if this is a nested module function call: Parent.Child.symbol(args)
        if isinstance(expr.object, MemberAccess):
            # Check if it's a chain of module accesses
            inner_module_sym = self._resolve_module_chain(expr.object)
            if inner_module_sym and inner_module_sym.namespace:
                from namespace import SymbolKind
                symbol = inner_module_sym.namespace.resolve(expr.method_name)
                if symbol and symbol.kind == SymbolKind.FUNCTION:
                    # Generate a direct function call (all modules are merged)
                    return self._generate_module_function_call(expr)
                elif symbol and symbol.kind == SymbolKind.STRUCT:
                    # Generate struct initialization
                    return self._generate_module_struct_init(expr)

        # Check if this is a module function call or struct init: ModuleName.symbol(args)
        if isinstance(expr.object, Identifier):
            if expr.object.name in self.namespace.modules:
                module_sym = self.namespace.modules[expr.object.name]
                if module_sym.namespace:
                    from namespace import SymbolKind
                    symbol = module_sym.namespace.resolve(expr.method_name)
                    if symbol and symbol.kind == SymbolKind.FUNCTION:
                        # Generate a direct function call (all modules are merged)
                        return self._generate_module_function_call(expr)
                    elif symbol and symbol.kind == SymbolKind.STRUCT:
                        # Generate struct initialization
                        return self._generate_module_struct_init(expr)

        # Check if this is a static method call: StructName.method(args) (use namespace)
        if isinstance(expr.object, Identifier):
            struct_name = expr.object.name
            if self.namespace.is_static_method(struct_name, expr.method_name):
                return self._generate_static_method_call(expr, struct_name)

        # Check if this is actually an enum initialization
        # Check both concrete enums and generic enums
        if isinstance(expr.object, Identifier):
            is_enum = expr.object.name in self.enum_types
            is_generic_enum = expr.object.name in self.generic_enums
            if is_enum or is_generic_enum:
                # Convert to EnumInit and generate it
                enum_init = EnumInit(
                    enum_name=expr.object.name,
                    variant_name=expr.method_name,
                    arguments=expr.arguments,
                    type_args=expr.object.type_args,  # Pass type_args for generic enums
                    line=expr.line,
                    column=expr.column
                )
                return self._generate_enum_init(enum_init)

        # Otherwise, it's a method call
        # Get mangled method name first to check if method expects mutable self
        # We need this info before generating the object expression
        # First, determine struct type by generating the object
        obj_val = self._generate_expression(expr.object)

        # Determine the struct type
        # For identified types, we can get the name directly
        struct_name = None
        obj_type = obj_val.type
        if hasattr(obj_type, 'name') and obj_type.name in self.struct_types:
            # Identified type - name is directly available
            struct_name = obj_type.name
        else:
            # Fallback to string comparison for literal types
            for name, (llvm_type, _) in self.struct_types.items():
                if str(obj_type) == str(llvm_type):
                    struct_name = name
                    break

        # Check for primitive type extensions (String)
        if struct_name is None:
            # String is i8* (pointer to i8)
            if isinstance(obj_type, ir.PointerType):
                pointee = obj_type.pointee
                if isinstance(pointee, ir.IntType) and pointee.width == 8:
                    struct_name = "String"

        if struct_name is None:
            raise ValueError(f"Cannot determine struct type for method call to {expr.method_name}")

        # Get mangled method name
        mangled_name = self._mangle_method_name(struct_name, expr.method_name)

        # Look up the method function
        if mangled_name not in self.functions:
            raise ValueError(f"Undefined method: {struct_name}.{expr.method_name}")

        method_func = self.functions[mangled_name]

        # Generate arguments: [self, arg1, arg2, ...]
        # Check if method expects mutable self (pointer to the value)
        # For String: immutable self is i8*, mutable self is i8**
        # For structs: immutable self is struct, mutable self is struct*
        self_arg = obj_val
        is_mutable_self = False
        if method_func.args:
            first_arg_type = method_func.args[0].type
            if struct_name == "String":
                # String is already i8*, so mutable self is i8** (pointer to pointer)
                if isinstance(first_arg_type, ir.PointerType):
                    pointee = first_arg_type.pointee
                    if isinstance(pointee, ir.PointerType):
                        is_mutable_self = True
            else:
                # Struct: mutable self is pointer to struct
                if isinstance(first_arg_type, ir.PointerType):
                    is_mutable_self = True

        if is_mutable_self:
            # Method expects pointer to self
            # If object is a variable, pass its alloca directly
            if isinstance(expr.object, Identifier) and expr.object.name in self.variables:
                self_arg = self.variables[expr.object.name]
            elif isinstance(expr.object, SelfExpr) and "self" in self.variables:
                # For 'self.method()' in a var self method, pass self's pointer directly
                self_ptr = self.variables["self"]
                # If self is already a pointer (var self method), use it directly
                if isinstance(self_ptr.type, ir.PointerType):
                    self_arg = self_ptr
                else:
                    self_arg = self_ptr  # It's an alloca, pass it
            elif isinstance(expr.object, MemberAccess):
                # Handle nested mutable access like self.keys.push(...)
                # We need a pointer to the field, not a copy
                self_arg = self._get_member_pointer(expr.object)
            else:
                # Otherwise create a temporary
                self_alloca = self.builder.alloca(obj_val.type, name="self_temp")
                self.builder.store(obj_val, self_alloca)
                self_arg = self_alloca

        args = [self_arg]  # self is first argument
        # Arguments are Argument objects with .value
        for arg in expr.arguments:
            args.append(self._generate_expression(arg.value))

        # Fill in default values for missing arguments
        if mangled_name in self.method_defaults:
            defaults = self.method_defaults[mangled_name]
            # defaults includes self, so adjust index: args[0] is self, defaults[0] is self
            for i in range(len(args), len(defaults)):
                if defaults[i] is not None:
                    args.append(self._generate_expression(defaults[i]))

        # Call the method
        return self.builder.call(method_func, args, name="methodcall")

    def _generate_static_method_call(self, expr: MethodCall, struct_name: str):
        """Generate a static method call: StructName.method(args)"""
        mangled_name = self._mangle_method_name(struct_name, expr.method_name)

        if mangled_name not in self.functions:
            raise ValueError(f"Undefined static method: {struct_name}.{expr.method_name}")

        method_func = self.functions[mangled_name]

        # Generate provided arguments
        args = []
        for arg in expr.arguments:
            args.append(self._generate_expression(arg.value))

        # Fill in default values for missing arguments
        if mangled_name in self.method_defaults:
            defaults = self.method_defaults[mangled_name]
            for i in range(len(args), len(defaults)):
                if defaults[i] is not None:
                    args.append(self._generate_expression(defaults[i]))

        return self.builder.call(method_func, args, name="static_methodcall")

    def _resolve_module_chain(self, expr: MemberAccess):
        """Resolve a chain of module accesses like Parent.Child to get the final ModuleSymbol.

        Returns the ModuleSymbol if the entire chain is modules, None otherwise.
        """
        if isinstance(expr.object, Identifier):
            # Base case: Parent.Child where Parent is a module
            if expr.object.name in self.namespace.modules:
                parent_module = self.namespace.modules[expr.object.name]
                if parent_module.namespace and expr.member in parent_module.namespace.modules:
                    return parent_module.namespace.modules[expr.member]
        elif isinstance(expr.object, MemberAccess):
            # Recursive case: GrandParent.Parent.Child
            parent_module = self._resolve_module_chain(expr.object)
            if parent_module and parent_module.namespace and expr.member in parent_module.namespace.modules:
                return parent_module.namespace.modules[expr.member]
        return None

    def _generate_module_function_call(self, expr: MethodCall):
        """Generate a module function call: ModuleName.function(args)

        Since all modules are merged, we can call the function directly.
        """
        func_name = expr.method_name

        if func_name not in self.functions:
            raise ValueError(f"Undefined function in module: {expr.object.name}.{func_name}")

        func = self.functions[func_name]

        # Generate arguments
        args = []
        for arg in expr.arguments:
            args.append(self._generate_expression(arg.value))

        return self.builder.call(func, args, name="module_call")

    def _generate_module_struct_init(self, expr: MethodCall):
        """Generate a module struct initialization: ModuleName.StructName(args)

        Since all modules are merged, the struct exists in the global namespace.
        """
        struct_name = expr.method_name

        # Convert MethodCall to StructInit
        struct_init = StructInit(
            struct_name=struct_name,
            field_inits=[],
            type_args=None,
            line=expr.line,
            column=expr.column
        )

        # Handle arguments
        # struct_types[name] = (llvm_type, field_order) where field_order is a list
        if struct_name in self.struct_types:
            _, field_order = self.struct_types[struct_name]

            # Map arguments to fields
            for i, arg in enumerate(expr.arguments):
                if arg.name:
                    # Named argument
                    struct_init.field_inits.append((arg.name, arg.value))
                elif i < len(field_order):
                    # Positional argument - map to field by order
                    struct_init.field_inits.append((field_order[i], arg.value))

        return self._generate_struct_init(struct_init)

    def _get_member_pointer(self, expr: MemberAccess):
        """Get a pointer to a struct field for mutable access.

        For expressions like self.keys where we need to mutate keys in place,
        this returns a GEP pointer to the field rather than extracting a copy.
        """
        # Get pointer to the base object
        if isinstance(expr.object, Identifier) and expr.object.name in self.variables:
            base_ptr = self.variables[expr.object.name]
        elif isinstance(expr.object, SelfExpr) and "self" in self.variables:
            base_ptr = self.variables["self"]
        elif isinstance(expr.object, MemberAccess):
            # Recursive case: nested member access like a.b.c
            base_ptr = self._get_member_pointer(expr.object)
        else:
            # Fallback: create temporary (won't propagate changes back)
            base_val = self._generate_expression(expr.object)
            base_ptr = self.builder.alloca(base_val.type, name="member_temp")
            self.builder.store(base_val, base_ptr)

        # Determine the struct type
        ptr_type = base_ptr.type
        if isinstance(ptr_type, ir.PointerType):
            struct_type = ptr_type.pointee
        else:
            raise ValueError(f"Expected pointer type, got {ptr_type}")

        # Find struct name
        struct_name = None
        if hasattr(struct_type, 'name') and struct_type.name in self.struct_types:
            struct_name = struct_type.name
        else:
            for name, (llvm_type, _) in self.struct_types.items():
                if str(struct_type) == str(llvm_type):
                    struct_name = name
                    break

        if struct_name is None:
            raise ValueError(f"Cannot find struct type for member access: {expr.member}")

        # Get field index
        _, field_order = self.struct_types[struct_name]
        if expr.member not in field_order:
            raise ValueError(f"Unknown field: {struct_name}.{expr.member}")
        field_index = field_order.index(expr.member)

        # GEP to get pointer to the field
        zero = ir.Constant(ir.IntType(32), 0)
        field_idx = ir.Constant(ir.IntType(32), field_index)
        return self.builder.gep(base_ptr, [zero, field_idx], name=f"{expr.member}_ptr")

    def _generate_self_expr(self, expr: SelfExpr):
        """Generate code for 'self' keyword."""
        if "self" not in self.variables:
            raise ValueError("'self' not found in current scope")

        # Load self from its alloca
        return self.builder.load(self.variables["self"], name="self")

    def _generate_enum_init(self, expr: EnumInit):
        """Generate code for enum variant initialization."""
        # Handle generic enum with type_args
        enum_name = expr.enum_name
        if expr.type_args:
            enum_name = self._ensure_monomorphized_enum(expr.enum_name, expr.type_args)

        if enum_name not in self.enum_types:
            raise ValueError(f"Undefined enum: {enum_name}")

        llvm_enum_type, variant_tags, variant_info = self.enum_types[enum_name]
        tag_value = variant_tags[expr.variant_name]
        variant_params = variant_info[expr.variant_name]

        # Check if this is a simple enum (just i32) or enum with payload
        if isinstance(llvm_enum_type, ir.IntType):
            # Simple enum: just return the tag value
            return ir.Constant(ir.IntType(32), tag_value)
        else:
            # Enum with payload: { i32 tag, [N x i8] payload }
            # Create undefined struct value
            enum_val = ir.Constant(llvm_enum_type, ir.Undefined)

            # Insert tag value
            tag_const = ir.Constant(ir.IntType(32), tag_value)
            enum_val = self.builder.insert_value(enum_val, tag_const, 0, name="enum_with_tag")

            # If this variant has associated values, pack them into payload
            if variant_params:
                # Generate values for arguments
                # Arguments are Argument objects with .value and optional .name
                arg_values = []

                # Build a dict for named args, list for positional
                arg_dict = {}
                arg_list = []
                for arg in expr.arguments:
                    if arg.is_named:
                        arg_dict[arg.name] = arg.value
                    else:
                        arg_list.append(arg.value)

                # Match arguments to parameters (named takes precedence, then positional)
                for i, (param_name, param_type) in enumerate(variant_params):
                    if param_name in arg_dict:
                        arg_val = self._generate_expression(arg_dict[param_name])
                    elif i < len(arg_list):
                        arg_val = self._generate_expression(arg_list[i])
                    else:
                        raise ValueError(f"Missing argument for parameter {param_name}")
                    arg_values.append(arg_val)

                # Create a struct for the associated values
                param_struct_type = ir.LiteralStructType([self._get_llvm_type(t) for _, t in variant_params])
                param_struct = ir.Constant(param_struct_type, ir.Undefined)
                for i, val in enumerate(arg_values):
                    param_struct = self.builder.insert_value(param_struct, val, i, name=f"param{i}")

                # Cast the param struct to bytes and store in payload
                # For simplicity, we'll use bitcast + store
                payload_array_type = llvm_enum_type.elements[1]  # [N x i8]

                # Allocate temporary space for the payload
                payload_temp = self.builder.alloca(param_struct_type, name="payload_temp")
                self.builder.store(param_struct, payload_temp)

                # Bitcast to array of bytes
                payload_ptr = self.builder.bitcast(payload_temp,
                                                   ir.PointerType(ir.IntType(8)),
                                                   name="payload_bytes_ptr")

                # Load bytes into an array value
                payload_bytes = ir.Constant(payload_array_type, ir.Undefined)
                for i in range(payload_array_type.count):
                    idx_ptr = self.builder.gep(payload_ptr,
                                              [ir.Constant(ir.IntType(32), i)],
                                              inbounds=True)
                    byte_val = self.builder.load(idx_ptr, name=f"byte{i}")
                    payload_bytes = self.builder.insert_value(payload_bytes, byte_val, i, name=f"payload{i}")

                # Insert payload into enum
                enum_val = self.builder.insert_value(enum_val, payload_bytes, 1, name="enum_with_payload")

            return enum_val
