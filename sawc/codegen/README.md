# Codegen Module

**IMPORTANT: This documentation must be kept in sync with the code. Any changes to the codegen module should be reflected here.**

## Overview

The `codegen` module generates LLVM IR from the Saw AST using llvmlite. The implementation uses a mixin-based architecture where the main `CodeGenerator` class inherits from multiple focused mixin classes, each responsible for a specific aspect of code generation.

## Architecture

```
CodeGenerator (core.py)
    ├── MatchMixin (match.py)
    ├── StructsMixin (structs.py)
    ├── CollectionsMixin (collections.py)
    ├── CallsMixin (calls.py)
    ├── OperatorsMixin (operators.py)
    ├── StatementsMixin (statements.py)
    ├── MethodsMixin (methods.py)
    ├── LoopsMixin (loops.py)
    ├── ConditionalsMixin (conditionals.py)
    ├── OptionalsMixin (optionals.py)
    ├── ClosuresMixin (closures.py)
    ├── GenericsMixin (generics.py)
    ├── TypesMixin (types.py)
    └── ResourcesMixin (resources.py)
```

All mixins share state through `self` - they access `self.builder`, `self.variables`, `self.functions`, etc. defined in `core.py`.

## File Descriptions

### `__init__.py`
Package initialization. Exports `CodeGenerator` for external use:
```python
from codegen import CodeGenerator
```

### `core.py` (659 lines)
Main `CodeGenerator` class with:
- **State initialization**: LLVM module, builder, symbol tables
- **`generate(program)`**: Main entry point, orchestrates code generation
- **Declaration methods**: `_declare_function`, `_declare_extern_function`, `_declare_extension_methods`
- **Registration methods**: `_register_struct`, `_register_enum`, `_register_concrete_enum`
- **Expression dispatch**: `_generate_expression` with visitor pattern (`visit_*` methods)
- **`compile_to_object(path)`**: Compiles LLVM IR to object file

#### Key State Variables
| Variable | Type | Purpose |
|----------|------|---------|
| `self.module` | `ir.Module` | LLVM module being built |
| `self.builder` | `ir.IRBuilder` | Current instruction builder |
| `self.variables` | `dict[str, ir.Value]` | Variable name → alloca instruction |
| `self.variable_types` | `dict[str, SawType]` | Variable name → Saw type |
| `self.functions` | `dict[str, ir.Function]` | Function name → LLVM function |
| `self.struct_types` | `dict` | Struct name → (LLVM type, field order) |
| `self.enum_types` | `dict` | Enum name → (LLVM type, variant tags, variant info) |
| `self.loop_stack` | `list[tuple]` | Stack of (continue_block, break_block, result_storage, cleanup_depth) |
| `self.cleanup_stack` | `list[list]` | Stack of variables needing cleanup per scope |
| `self.type_param_context` | `dict[str, SawType]` | Type parameter substitutions during monomorphization |

### `types.py` (251 lines)
LLVM type conversion and utilities.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_get_llvm_type(saw_type)` | Convert SawType to LLVM type |
| `_resolve_type_alias(saw_type)` | Resolve type aliases to concrete types |
| `_type_to_string(saw_type)` | Convert type to string for name mangling |
| `_mangle_method_name(struct, method, params)` | Generate unique method names |
| `_is_optional_type(llvm_type)` | Check if type is optional `{i1, T}` |
| `_wrap_in_optional(value)` | Wrap value in Some optional |

### `resources.py` (206 lines)
Resource management: cleanup, deinit, and copy behavior.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_get_cleanup_behavior(saw_type)` | Returns "deinit", "implicit_copy", "no_copy", or "none". `ExplicitCopy` types map to "deinit" (they have a deinit and are never implicitly copied — the typechecker enforces `move`/`.copy()`). |
| `_needs_cleanup(saw_type)` | Check if type needs cleanup on scope exit |
| `_generate_deinit_call(var_name, var_type)` | Generate call to deinit method |
| `_generate_copy(value, saw_type)` | Generate a call to `copy()` (for `Copy` at transfer sites, and for explicit `.copy()` on `Copy`/`ExplicitCopy` types) |
| `_cleanup_scope(scope_vars)` | Clean up variables in a scope |
| `_cleanup_all_scopes()` | Clean up all scopes (for return statements) |
| `_needs_copy_for_struct_init(expr, field_type)` | Check if field needs copying |

### `mangle.py`
Canonical name mangling — the single source of truth for turning Saw types and
generic instantiations into unique LLVM-identifier strings. Every producer that
registers a specialized struct/enum/function and every consumer that looks one
up goes through `mangle_type` (total over `TypeKind`, injective, so
`Result<(Int,Int),E>` and `Result<(String,Bool),E>` never collide). `generics.py`,
`types.py`, and `results.py` delegate here rather than hand-rolling names.

### `generics.py` (446 lines)
Monomorphization of generic types and functions.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_mangle_generic_name(base, type_args)` | Create mangled name like `Box_Int` |
| `_instantiate_generic_function(name, type_args)` | Monomorphize a generic function |
| `_ensure_monomorphized_struct(name, type_args)` | Ensure struct instantiation exists |
| `_ensure_monomorphized_enum(name, type_args)` | Ensure enum instantiation exists |
| `_monomorphize_extension(ext, struct_name, type_args)` | Monomorphize extension methods |

#### Monomorphization Process
1. When a generic type/function is used with concrete types (e.g., `Box<Int>`)
2. Check if monomorphized version exists in `generated_instantiations`
3. If not, substitute type parameters and generate specialized version
4. Store in appropriate table with mangled name

### `closures.py` (194 lines)
Closure generation with environment capture.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_closure(expr)` | Generate closure struct with fn_ptr and env_ptr |
| `_analyze_captures(body, params)` | Find variables captured from enclosing scope |

#### Closure Representation
Closures are represented as `{fn_ptr, env_ptr}` structs where:
- `fn_ptr`: Pointer to generated function (first param is env pointer)
- `env_ptr`: Pointer to captured environment struct

### `optionals.py` (238 lines)
Optional type handling: None, unwrap, coalesce, chaining.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_none_literal(expr)` | Generate None value `{false, undef}` |
| `_generate_force_unwrap(expr)` | Generate `!` operator with panic on None |
| `_generate_nil_coalesce(expr)` | Generate `??` operator |
| `_generate_optional_chain(expr)` | Generate `?.` operator |

#### Optional Representation
Optionals are `{i1, T}` structs where:
- First element: `true` for Some, `false` for None
- Second element: The value (undefined for None)

### `conditionals.py` (410 lines)
If expressions, if-let, and guard-let.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_if_expression(expr)` | Generate if/else with phi node for result |
| `_generate_if_let_expression(expr)` | Generate if-let optional binding |
| `_generate_guard_let_statement(stmt)` | Generate guard-let with early exit |

#### Control Flow Pattern
```
if condition:        if let value = optional:
  then_block    →      check is_some
else:                  then_block (with binding)
  else_block         else:
merge_block            else_block (early exit)
                     merge_block
```

### `loops.py` (419 lines)
While loops, for loops, break, and continue.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_while_expr(expr)` | Generate while loop (conditional or infinite) |
| `_generate_for_loop(expr)` | Generate for loop over range or iterator |
| `_generate_break_statement(stmt)` | Generate break (with optional value) |
| `_generate_continue_statement(stmt)` | Generate continue |

#### Loop Stack
`self.loop_stack` tracks nested loops as `(continue_block, break_block, result_storage, cleanup_depth)`:
- `continue_block`: Target for continue statements
- `break_block`: Target for break statements
- `result_storage`: Alloca for loop expression result (None for statement context)
- `cleanup_depth`: `len(self.cleanup_stack)` at loop entry — the boundary
  `break`/`continue` unwind to (`_cleanup_to_depth` in `resources.py`, DF-218r).
  That walk is shared: the `try`/`catch` error edge unwinds to the TRY BLOCK's
  entry depth through the same function, bounded by `_catch_context`'s fifth
  element (DF-218v)

### `methods.py` (362 lines)
Method and function body generation.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_function(func, name_override)` | Generate function body |
| `_generate_method(struct_name, method)` | Generate instance method |
| `_generate_init_method(struct_name, method)` | Generate custom init method |
| `_generate_static_method(struct_name, method)` | Generate static method |
| `_generate_block(block, manage_cleanup)` | Generate block with cleanup |
| `_generate_field_deinit_calls(struct_name)` | Auto-call deinit on struct fields |

#### Method Types
| Type | Self Parameter | Returns |
|------|---------------|---------|
| Instance | `&self` (immutable ref) or `&var self` (mutable ref) | Any |
| Static | None | Any |
| Init | None | Struct value |
| Deinit | `&var self` (mutable ref) | Void |

### `statements.py` (393 lines)
Statement generation: let, assign, return.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_let_statement(stmt)` | Generate let binding with optional wrapping |
| `_generate_assign_statement(stmt)` | Generate assignment to variable/field/index |
| `_generate_return_statement(stmt)` | Generate return with cleanup |
| `_expr_type(expr)` | Read a checked expression's type annotation, substituting generic bindings (fail-loud) |

#### Assignment Targets
- Simple variable: `x = value`
- Field: `obj.field = value`
- Array/pointer index: `arr[i] = value`

### `operators.py` (263 lines)
Binary and unary operators, casts, moves.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_binary_op(expr)` | Generate binary operation |
| `_generate_logical_and(expr)` | Short-circuit && |
| `_generate_logical_or(expr)` | Short-circuit \|\| |
| `_generate_unary_op(expr)` | Generate unary operation (-, not) |
| `_generate_move_expr(expr)` | Generate move (marks variable as moved) |
| `_generate_cast_expr(expr)` | Generate type cast |

#### Short-Circuit Evaluation
```
a && b:                    a || b:
  eval a                     eval a
  if false → result=false    if true → result=true
  else → result=b            else → result=b
```

### `calls.py` (582 lines)
Function calls, method calls, built-ins, enum initialization.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_function_call(expr)` | Generate function call (handles closures, generics) |
| `_generate_print(arguments)` | Generate print built-in |
| `_generate_sizeof(expr)` | Generate sizeof<T>() built-in |
| `_generate_method_call(expr)` | Generate method call (instance, static, module) |
| `_generate_static_method_call(expr, struct_name)` | Generate static method call |
| `_generate_enum_init(expr)` | Generate enum variant initialization |
| `_generate_self_expr(expr)` | Generate self keyword |
| `_get_member_pointer(expr)` | Get GEP pointer to struct field |

#### Method Call Resolution
1. Check for nested module access (`Parent.Child.func()`)
2. Check for module function/struct (`Module.func()`)
3. Check for static method (`Struct.method()`)
4. Check for enum initialization (`Enum.Variant()`)
5. Otherwise: instance method (`obj.method()`)

### `collections.py` (103 lines)
Tuple and array literals and indexing.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_tuple_literal(expr)` | Generate tuple as LLVM struct |
| `_generate_tuple_index(expr)` | Generate tuple element extraction |
| `_generate_array_literal(expr)` | Generate array as LLVM array |
| `_generate_array_index(expr)` | Generate array/tuple/pointer indexing |

### `structs.py` (151 lines)
Struct initialization and member access.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_struct_init(expr)` | Generate struct initialization (field or custom init) |
| `_generate_member_access(expr)` | Generate field access or enum variant access |

#### Struct Init Modes
1. **Field initialization**: `Point(x: 1, y: 2)` → direct field assignment
2. **Custom init**: `Point(magnitude: 5)` → calls init method

### `match.py` (142 lines)
Match expressions on enum types.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_generate_match_expr(expr)` | Generate match with switch on enum tag |

#### Match Generation
1. Extract tag from enum value
2. Create basic block for each arm
3. Generate switch instruction with tag cases
4. For each arm: extract bindings, generate body, branch to merge
5. Create phi node at merge block for result

## Adding New Features

When adding new code generation features:

1. **Identify the category** - Which mixin does it belong to?
2. **Add the method** - Implement in the appropriate mixin file
3. **Add visitor if needed** - If it's a new expression type, add `visit_*` in `core.py`
4. **Update this documentation** - Add method to the appropriate table
5. **Run tests** - Ensure the full suite stays green (`make test`)

## Testing

```bash
make test           # Run all tests
make test-verbose   # Run with verbose output
make test-filter FILTER=enum  # Run tests matching pattern
```
