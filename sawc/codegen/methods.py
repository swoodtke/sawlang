"""
Method and function generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for functions,
methods (instance, static, init), and extension methods.

Usage:
    class CodeGenerator(MethodsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import (
    Function, Block, Method, Extension, SawType, TypeKind
)
from .mangle import mangle_named


class MethodsMixin:
    """Mixin providing method and function generation for CodeGenerator.

    Methods:
        _generate_extension_methods: Generate all methods in an extension
        _generate_method: Generate a single instance method
        _generate_field_deinit_calls: Generate deinit calls for struct fields
        _generate_init_method: Generate a custom init method
        _generate_static_method: Generate a static method
        _generate_function: Generate a function body
        _generate_block: Generate a block of statements
    """

    def _generate_extension_methods(self, extension: Extension):
        """Generate code for all methods in an extension."""
        # Skip generic extensions - they'll be monomorphized when the struct is used
        if extension.type_params:
            return

        # Set Self type context for this extension
        old_self_context = self.self_type_context
        self.self_type_context = extension.struct_name

        for method in extension.methods:
            # Design 40 item 9 (C6): generic methods are monomorphized on demand
            # per call-site method type args, not generated eagerly.
            if getattr(method, 'type_params', None) and not method.is_init:
                continue
            if method.is_init:
                self._generate_init_method(extension.struct_name, method)
            elif method.is_static:
                self._generate_static_method(extension.struct_name, method)
            else:
                self._generate_method(extension.struct_name, method)

        # Restore Self type context
        self.self_type_context = old_self_context

    def _generate_method(self, struct_name: str, method: Method):
        """Generate code for a single instance method."""
        # Overloading (design 55): use the AST-stamped overload symbol if present.
        mangled_name = (getattr(method, 'mangled_symbol', None)
                        or self._mangle_method_name(struct_name, method.name))
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # design 69: attach the DISubprogram + prime the line location.
        self._di_begin_function(llvm_func, f"{struct_name}.{method.name}",
                                getattr(method, 'source_file', ''),
                                getattr(method, 'line', 0))

        # Clear variables and cleanup stack for this method
        self.variables = {}
        self.void_variables = set()
        self.variable_types = {}
        self.cleanup_stack = []
        self.drop_flags = {}
        # Per-function reset: `moved_variables` is keyed by bare NAME, so without
        # this a name moved in one function would suppress the drop of a same-named
        # (flag-less) binding in the next function generated (design 65 followup).
        self.moved_variables = set()

        # Determine the Self type for this extension
        self_llvm_type, self_saw_type = self._ext_self_types(struct_name)

        # Create allocas for parameters (including self)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            # For mutable self, it's already a pointer - just store it directly
            if i == 0 and param.name == "self" and method.self_mutable:
                self.variables[param.name] = llvm_func.args[i]
                self.variable_types[param.name] = self_saw_type
            elif param.name == "self":
                # Handle 'self' parameter - use the Self type
                alloca = self._entry_alloca(self_llvm_type, name=param.name)
                self.builder.store(llvm_func.args[i], alloca)
                self.variables[param.name] = alloca
                self.variable_types[param.name] = self_saw_type
            else:
                alloca = self._entry_alloca(self._get_llvm_type(param.type), name=param.name)
                self.builder.store(llvm_func.args[i], alloca)
                self.variables[param.name] = alloca
                self.variable_types[param.name] = param.type

        # Set current return type for implicit optional wrapping
        old_return_type = self.current_return_type
        self.current_return_type = method.return_type

        # A compiler-derived memberwise copy() has no user body: synthesize one
        # here, where every field's copy tier is known from the namespace.
        if getattr(method, 'is_derived_copy', False):
            self._generate_derived_copy_body(struct_name)
            self.current_return_type = old_return_type
            return

        # A compiler-derived memberwise equals() (design 32): compare self and
        # other field by field via the shared Equatable lowering.
        if getattr(method, 'is_derived_equals', False):
            self._generate_derived_equals_body(struct_name)
            self.current_return_type = old_return_type
            return

        # A compiler-derived lexicographic compare() / field-streaming hash()
        # (design 48) have no user body either; emit them from the field layout.
        if getattr(method, 'is_derived_compare', False):
            self._generate_derived_compare_body(struct_name)
            self.current_return_type = old_return_type
            return
        if getattr(method, 'is_derived_hash', False):
            self._generate_derived_hash_body(struct_name)
            self.current_return_type = old_return_type
            return

        # Generate method body
        result = self._generate_block(method.body)

        # For deinit methods, auto-call deinit on fields that implement Deinit
        if method.name == "deinit" and not self.builder.block.is_terminated:
            self._generate_field_deinit_calls(struct_name)

        # Handle return
        if method.return_type.kind == TypeKind.VOID:
            if not self.builder.block.is_terminated:
                self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                if result is not None:
                    self.builder.ret(self._coerce_ret_value(result))
                else:
                    # Degenerate fallthrough (every reachable path already
                    # returned, e.g. an if/else where both arms `return`): emit an
                    # `undef` of the return type. `ir.Constant(t, 0)` is INVALID for
                    # an aggregate (struct/enum/optional/array/tuple) — `0` is not
                    # an iterable field list, so llvmlite's `format_constant` ICE'd
                    # ("'int' object is not iterable") at `ret` emission (DF8).
                    default = ir.Constant(self._get_llvm_type(method.return_type),
                                          ir.Undefined)
                    self.builder.ret(default)

        # Restore return type
        self.current_return_type = old_return_type

    def _generate_field_deinit_calls(self, struct_name: str):
        """Release the struct's cleanup-needing fields at the end of its deinit.

        Appended after a user-declared `deinit` body so nested resources are
        destroyed AFTER the user's own cleanup, in reverse declaration order
        (LIFO). Delegates to the shared recursive drop routine so a field that is
        itself a struct-holding-resources recurses, and String/Deinit fields hit
        their release. `struct_name` is the (possibly monomorphized) key into
        `struct_types`; reconstruct the SawType so field types resolve.
        """
        self_ptr = self.variables.get("self")
        if self_ptr is None:
            return
        # Non-generic structs key struct_types by their plain name, which is also
        # the SawType.struct_name; monomorphized deinit bodies don't reach here
        # (see _generate_method_generic), so a plain STRUCT SawType suffices.
        self_type = SawType(TypeKind.STRUCT, struct_name=struct_name)
        self._emit_field_cleanup_at(self_ptr, self_type)

    def _generate_derived_copy_body(self, struct_name: str):
        """Emit the body of a compiler-derived memberwise copy().

        Builds a fresh struct value from self's fields: POD fields are copied
        bitwise, while fields whose type declares ImplicitCopy/ExplicitCopy have
        their own copy() invoked. A NoCopy field is rejected by the typechecker
        (`_check_derivable_copy`) before reaching here.

        `self` is immutable (`&self`), so codegen passes it by value; the entry
        block stored it into an alloca, which we index into.
        """
        llvm_struct_type, field_order = self.struct_types[struct_name]
        field_types = self.namespace.get_struct_fields(struct_name) or {}
        self_ptr = self.variables.get("self")

        result = ir.Constant(llvm_struct_type, ir.Undefined)
        for i, field_name in enumerate(field_order):
            field_type = field_types.get(field_name)
            field_ptr = self.builder.gep(self_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), i)
            ], name=f"{field_name}_ptr")
            field_val = self.builder.load(field_ptr, name=field_name)

            # design 139: two field kinds have their copy derived INLINE and so
            # own no `copy` symbol for the lookup below to find. Both must be
            # handled before it, because falling through would either raise on a
            # symbol that cannot exist (an enum) or, worse, silently bitwise-alias
            # an owning field (an optional, whose conformance name is None, so it
            # never even reached the check).
            conf_name = self._get_type_name_for_conformance(field_type) if field_type else None
            conformances = self.namespace.get_conformances(conf_name) if conf_name else []
            # A field annotated with a bare enum name reaches here tagged STRUCT
            # (the parser defaults an unknown capitalized name that way, and not
            # every path re-resolves it), so retag before asking.
            enum_field = (self.namespace._normalize_struct_enum(field_type)
                          if field_type is not None else None)
            inline_enum_copy = (
                enum_field is not None
                and enum_field.kind == TypeKind.ENUM
                and enum_field.enum_name is not None
                and self.namespace.declared_copy_tier(enum_field.enum_name)
                in ('implicit', 'explicit'))
            if inline_enum_copy:
                field_val = self._emit_enum_deep_copy(field_val, enum_field)
            elif field_type is not None and field_type.kind == TypeKind.OPTIONAL:
                field_val = self._emit_optional_deep_copy(field_val, field_type)
            # Does this field's type carry its own copy()? (ImplicitCopy or
            # ExplicitCopy). If so, invoke it; otherwise the load is a bitwise copy.
            elif "ImplicitCopy" in conformances or "ExplicitCopy" in conformances:
                copy_fn = self._field_copy_fn(field_type)
                if copy_fn is None:
                    # The field's type declares a copy policy, so it HAS a
                    # `copy()`; failing to find the symbol would silently emit a
                    # bitwise alias of an owning field, and both copies would
                    # then free the same storage. Refuse instead.
                    raise RuntimeError(
                        f"internal compiler error: no `copy` symbol for field "
                        f"`{field_name}` of type `{field_type}` while deriving "
                        f"copy() for `{struct_name}`")
                field_val = self.builder.call(copy_fn, [field_val],
                                              name=f"{field_name}_copy")

            result = self.builder.insert_value(result, field_val, i)

        self.builder.ret(self._coerce_ret_value(result))

    def _field_copy_fn(self, field_type):
        """The emitted `copy` function for a struct field's type, or None.

        `_type_method_base` mangles the field type exactly as written, but a
        field declared `Vector<Int>` denotes `Vector<Int, GlobalAllocator>` and
        the monomorphized method is registered under the FULL form — so the
        written form alone looks for `Vector$1$Int_copy` against an emitted
        `Vector$2$Int$GlobalAllocator_copy` and misses. Fill the declared
        defaults (design 37) and try that name first.

        Scoped to the derived-copy body deliberately: `_type_method_base` feeds
        the drop glue as well, and filling defaults there changes which struct
        fields get a real `deinit` call across the whole compiler. See DF-128c.
        """
        if field_type is None:
            return None
        base = self._type_method_base(field_type)
        if base is None:
            return None
        candidates = []
        if field_type.kind in (TypeKind.STRUCT, TypeKind.ENUM):
            name = (field_type.struct_name if field_type.kind == TypeKind.STRUCT
                    else field_type.enum_name)
            args = list(field_type.type_args or [])
            filled = self._fill_default_type_args(name, args) if name else args
            if len(filled) != len(args):
                candidates.append(mangle_named(name, filled))
        candidates.append(base)
        for cand in candidates:
            fn = self.functions.get(self._mangle_method_name(cand, "copy"))
            if fn is not None:
                return fn
        return None

    def _generate_derived_equals_body(self, struct_name: str):
        """Emit the body of a compiler-derived memberwise equals() (design 32).

        `self` (`&self`) and `other` (by value) were each stored into an alloca
        by the entry block; load both and compare field by field via the shared
        Equatable lowering, which recurses into String / nested struct / enum
        fields. Non-Equatable fields were rejected by `_check_derivable_equals`.
        """
        self_ptr = self.variables.get("self")
        other_ptr = self.variables.get("other")
        self_val = self.builder.load(self_ptr, name="self_val")
        other_val = self.builder.load(other_ptr, name="other_val")
        saw_type = SawType(TypeKind.STRUCT, struct_name=struct_name)
        result = self._emit_memberwise_equals(self_val, other_val, saw_type)
        self.builder.ret(self._coerce_ret_value(result))

    def _generate_derived_compare_body(self, struct_name: str):
        """Emit the body of a compiler-derived lexicographic compare() (design
        48): load self and other, compare field by field, return the Ordering."""
        self_ptr = self.variables.get("self")
        other_ptr = self.variables.get("other")
        self_val = self.builder.load(self_ptr, name="self_val")
        other_val = self.builder.load(other_ptr, name="other_val")
        saw_type = SawType(TypeKind.STRUCT, struct_name=struct_name)
        result = self._emit_memberwise_compare(self_val, other_val, saw_type)
        self.builder.ret(self._coerce_ret_value(result))

    def _generate_derived_hash_body(self, struct_name: str):
        """Emit the body of a compiler-derived field-streaming hash() (design
        48): stream each of self's fields into the `&var Hasher` param `h`. `h`
        is a reference param, so `self.variables['h']` is a Hasher** — load once
        to get the Hasher*."""
        self_ptr = self.variables.get("self")
        self_val = self.builder.load(self_ptr, name="self_val")
        hasher_slot = self.variables.get("h")
        hasher_ptr = self.builder.load(hasher_slot, name="hasher_ptr")
        saw_type = SawType(TypeKind.STRUCT, struct_name=struct_name)
        self._emit_memberwise_hash(self_val, saw_type, hasher_ptr)
        self.builder.ret_void()

    def _generate_init_method(self, struct_name: str, method: Method):
        """Generate code for a custom init method."""
        param_names = [p.name for p in method.parameters]
        mangled_name = self._mangle_method_name(struct_name, method.name, param_names)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # design 69: attach the DISubprogram + prime the line location.
        self._di_begin_function(llvm_func, f"{struct_name}.{method.name}",
                                getattr(method, 'source_file', ''),
                                getattr(method, 'line', 0))

        # Clear variables and cleanup stack for this method
        self.variables = {}
        self.void_variables = set()
        self.variable_types = {}
        self.cleanup_stack = []
        self.drop_flags = {}
        # Per-function reset: `moved_variables` is keyed by bare NAME, so without
        # this a name moved in one function would suppress the drop of a same-named
        # (flag-less) binding in the next function generated (design 65 followup).
        self.moved_variables = set()

        # Set current return type for None literal generation
        old_return_type = self.current_return_type
        self.current_return_type = method.return_type

        # Create allocas for parameters (no self for init methods)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            alloca = self._entry_alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca
            self.variable_types[param.name] = param.type

        # Generate method body - must return a struct value
        result = self._generate_block(method.body)

        # Handle return - init methods must return the struct
        if not self.builder.block.is_terminated:
            if result is not None:
                self.builder.ret(self._coerce_ret_value(result))
            else:
                # Error: init must return a struct
                # For now, return a default struct value
                struct_type, _ = self.struct_types[struct_name]
                default = ir.Constant(struct_type, ir.Undefined)
                self.builder.ret(default)

        # Restore previous return type
        self.current_return_type = old_return_type

    def _generate_static_method(self, struct_name: str, method: Method):
        """Generate code for a static method (no self parameter)."""
        # Overloading (design 55): use the AST-stamped overload symbol if present.
        mangled_name = (getattr(method, 'mangled_symbol', None)
                        or self._mangle_method_name(struct_name, method.name))
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # design 69: attach the DISubprogram + prime the line location.
        self._di_begin_function(llvm_func, f"{struct_name}.{method.name}",
                                getattr(method, 'source_file', ''),
                                getattr(method, 'line', 0))

        # Clear variables and cleanup stack for this method
        self.variables = {}
        self.void_variables = set()
        self.variable_types = {}
        self.cleanup_stack = []
        self.drop_flags = {}
        # Per-function reset: `moved_variables` is keyed by bare NAME, so without
        # this a name moved in one function would suppress the drop of a same-named
        # (flag-less) binding in the next function generated (design 65 followup).
        self.moved_variables = set()

        # Set current return type for None literal generation
        old_return_type = self.current_return_type
        self.current_return_type = method.return_type

        # Push a param cleanup scope (mirrors `_generate_function`): an owned
        # param a static factory does NOT move out on some path must be dropped
        # there, not leaked — this is what makes `Box.try_make`'s failure path
        # deinit the un-moved `value` cleanly (design 42).
        self.cleanup_stack.append([])

        # Create allocas for parameters (no self for static methods)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            alloca = self._entry_alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca
            self.variable_types[param.name] = param.type
            if self._needs_cleanup(param.type):
                self._register_cleanup(param.name, param.type)

        # Generate method body
        result = self._generate_block(method.body)

        # Handle return — clean the param scope on the fall-through path (explicit
        # `return`s inside the body already ran `_cleanup_all_scopes`).
        if not self.builder.block.is_terminated:
            self._cleanup_all_scopes()
            if method.return_type.kind == TypeKind.VOID:
                self.builder.ret_void()
            elif result is not None:
                self.builder.ret(self._coerce_ret_value(result))
            else:
                self.builder.ret_void()

        # Restore previous return type
        self.current_return_type = old_return_type

    def _generate_function(self, func: Function, name_override: str = None):
        """Generate a function body. If name_override is provided, use it instead of func.name."""
        func_name = name_override if name_override else func.name
        llvm_func = self.functions[func_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # design 69: attach the DISubprogram + prime the line location.
        self._di_begin_function(llvm_func, func.name,
                                getattr(func, 'source_file', ''),
                                getattr(func, 'line', 0))

        # Clear variables and cleanup stack for this function
        self.variables = {}
        self.void_variables = set()
        self.variable_types = {}
        self.cleanup_stack = []
        self.drop_flags = {}
        # Per-function reset: `moved_variables` is keyed by bare NAME, so without
        # this a name moved in one function would suppress the drop of a same-named
        # (flag-less) binding in the next function generated (design 65 followup).
        self.moved_variables = set()

        # Set current return type for None-literal generation and return-position
        # wrapping. Substitute against the active monomorphization context so that
        # a generic function returning `Result<T, E>` / `T?` builds and mangles
        # its Ok/Err/Some against the CONCRETE payload (e.g. Result<Int, Int>) —
        # otherwise Result auto-wrap looks up the unsubstituted `Result$2$T$E`
        # enum, which was never registered (brief 36, L7). Empty context (a
        # non-generic function) makes this a no-op.
        old_return_type = self.current_return_type
        self.current_return_type = self._substitute_saw_type(func.return_type, self.type_param_context)

        # The C entry `main` was declared `(argc, argv)` (design 81 CI rider):
        # stash both into the argv globals at the very top so `Env.argc`/`Env.arg`
        # can read them on every platform. Guarded on the emitted signature so a
        # user `main()` (no Saw params) is handled without touching its scope.
        if (func.name == "main" and not func.parameters
                and len(llvm_func.args) == 2
                and getattr(self, '_argc_global', None) is not None):
            self.builder.store(llvm_func.args[0], self._argc_global)
            self.builder.store(llvm_func.args[1], self._argv_global)

        # Create allocas for parameters and track for cleanup
        # Push a scope for function parameters (cleaned up when function returns)
        self.cleanup_stack.append([])
        for i, param in enumerate(func.parameters):
            llvm_func.args[i].name = param.name
            # Substitute the active monomorphization so a generic function's owning
            # param (`gtakes<T>(a: T)` with T = an Arc/String) is recognized as
            # cleanup-needing and released — an unsubstituted generic `T` reads as
            # non-owning and leaks (design 65).
            ptype = self._substitute_saw_type(param.type, self.type_param_context)
            alloca = self._entry_alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca
            self.variable_types[param.name] = param.type
            # Track parameter for cleanup if it needs it. An owned param can be
            # `move`d out on some paths but not others, so register it with a drop
            # flag (design 42) — this is what makes MakeBoxOr's failure path drop
            # the un-moved `value` cleanly instead of leaking it.
            if self._needs_cleanup(ptype):
                self._register_cleanup(param.name, ptype)

        # Generate function body (block manages its own cleanup scope)
        result = self._generate_block(func.body)

        # Handle return - cleanup parameter scope before returning. Read the
        # emitted signature, not `func.return_type`: for a generic instantiation
        # the declared type is still the type PARAMETER, so an `R = Void`
        # instantiation took the value-returning branch below and tried to build
        # an `undef` of void (design 132 unit C / DF-123b).
        returns_void = isinstance(llvm_func.function_type.return_type, ir.VoidType)
        if func.return_type.kind == TypeKind.VOID or returns_void:
            if not self.builder.block.is_terminated:
                # Cleanup parameter scope before return
                self._cleanup_all_scopes()
                # For main(), return 0 instead of void
                if func.name == "main" and not returns_void:
                    self.builder.ret(ir.Constant(ir.IntType(32), 0))
                else:
                    self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                # Cleanup parameter scope before return
                self._cleanup_all_scopes()
                if result is not None:
                    self.builder.ret(self._coerce_ret_value(result))
                else:
                    # Degenerate fallthrough (every reachable path already
                    # returned — e.g. an if/else where both arms `return`): emit an
                    # `undef` of the return type. `ir.Constant(t, 0)` is INVALID for
                    # an aggregate (struct/enum/optional/array/tuple) — `0` is not
                    # an iterable field list, so llvmlite's `format_constant` ICE'd
                    # ("'int' object is not iterable") at `ret` emission (DF8).
                    default = ir.Constant(self._get_llvm_type(func.return_type),
                                          ir.Undefined)
                    self.builder.ret(default)

        # Restore previous return type
        self.current_return_type = old_return_type

    def _generate_block(self, block: Block, manage_cleanup: bool = True):
        """Generate code for a block.

        Args:
            block: The block to generate code for
            manage_cleanup: If True, push/pop a cleanup scope for this block.
                          Set to False when the caller manages cleanup (e.g., functions).
        """
        # Push new cleanup scope for this block
        if manage_cleanup:
            self.cleanup_stack.append([])

        # Design 100: a binding inside this block may SHADOW an enclosing binding
        # of the same name (the blessed `let data = derive(data)` in a nested
        # scope). Snapshot the name->storage maps so the shadowed OUTER bindings
        # are restored when the block ends — otherwise a use of the outer name
        # after the block would resolve to this block's (already-dropped) inner
        # storage (a use-after-free). Only for a real block scope (a function body
        # manages its own frame and keeps its bindings).
        _shadow_snapshot = None
        if manage_cleanup:
            _shadow_snapshot = (dict(self.variables),
                                dict(self.variable_types),
                                dict(self.drop_flags))

        result = None

        # design 94: statement temps created while evaluating this block's
        # final_expr (an unbound method receiver, a discarded call result) must be
        # dropped on the paths that CREATE them — inside this block — not deferred
        # to the enclosing statement's cleanup point. A nested block is often a
        # conditional branch whose merge is also reached by a sibling branch that
        # never created the temp; dropping there releases an uninitialized slot
        # (a garbage pointer). Statements inside the block already drain their own
        # temps in `_generate_statement`, so only the final_expr's temps (those
        # added beyond this mark) need draining here. `statement_temps` is None
        # outside any statement context (e.g. a function body before its first
        # statement) — then there is nothing to confine.
        temp_mark = len(self.statement_temps) if self.statement_temps is not None else None

        for stmt in block.statements:
            self._generate_statement(stmt)
            if self.builder.block.is_terminated:
                # Early exit (return/break) already handled cleanup
                if manage_cleanup:
                    self.cleanup_stack.pop()
                    self._restore_shadow_snapshot(_shadow_snapshot)
                return None

        if block.final_expr is not None:
            # design 69: point the line table at the tail expression (an
            # expression-oriented block's value — e.g. a bare `panic(...)` — is a
            # final_expr, not a statement, so it needs its own location set here).
            self._di_set_line(getattr(block.final_expr, 'line', 0),
                              getattr(block.final_expr, 'column', 0))
            # Honor an ImplicitCopy `needs_copy` annotation on a tail-return final
            # expression (only the function/method body's final_expr is marked
            # by the value-transfer checkpoint, so other blocks are unaffected).
            result = self._gen_transfer_value(block.final_expr)

        # Drop final_expr statement temps confined to this block (design 94),
        # before the block's own scope-var cleanup (LIFO). Skip when the block
        # already terminated (a `return`/`break` drained via the scope machinery).
        if (manage_cleanup and temp_mark is not None
                and not self.builder.block.is_terminated):
            branch_temps = self.statement_temps[temp_mark:]
            if branch_temps:
                for slot, saw_type in reversed(branch_temps):
                    self._emit_drop_at(slot, saw_type)
                del self.statement_temps[temp_mark:]

        # Cleanup variables declared in this block
        if manage_cleanup:
            scope_vars = self.cleanup_stack.pop()
            if not self.builder.block.is_terminated:
                self._cleanup_scope(scope_vars)
            # Restore shadowed enclosing bindings (design 100) after this block's
            # own cleanup has run against its (inner) storage.
            self._restore_shadow_snapshot(_shadow_snapshot)

        return result

    def _restore_shadow_snapshot(self, snapshot):
        """Restore the name->storage maps captured at block entry (design 100),
        re-exposing any enclosing binding that this block's inner binding
        shadowed. Block-local (non-shadowing) names are left in place — they are
        out of scope and thus unreferenceable, so they never resolve wrongly."""
        if snapshot is None:
            return
        saved_vars, saved_types, saved_flags = snapshot
        self.variables.update(saved_vars)
        self.variable_types.update(saved_types)
        self.drop_flags.update(saved_flags)
