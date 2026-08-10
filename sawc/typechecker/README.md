# TypeChecker Module

**IMPORTANT: This documentation must be kept in sync with the code. Any changes to the typechecker module should be reflected here.**

## Overview

The `typechecker` module performs type checking and semantic analysis on the Saw AST. It validates type correctness, resolves symbols, checks trait conformance, and enforces resource management rules (the Copy trait family — `NoCopy`, `ImplicitCopy`, `ExplicitCopy`, `Deinit`) plus the Law of Exclusivity on `&var` paths. Value copies/moves all funnel through one value-transfer checkpoint. The implementation uses a mixin-based architecture where the main `TypeChecker` class inherits from multiple focused mixin classes.

## Architecture

```
TypeChecker (core.py)
    ├── ExpressionsMixin (expressions.py)
    ├── StatementsMixin (statements.py)
    ├── RegistrationMixin (registration.py)
    └── TypeUtilsMixin (types.py)
```

All type information is stored in the `Namespace` object using symbol classes defined in `namespace.py`:
- `StructSymbol` - Struct fields, methods, and type parameters
- `EnumSymbol` - Enum variants with associated values
- `TraitSymbol` - Trait methods and associated types
- `FunctionSymbol` - Function/method signature with params, return type, type params

## File Descriptions

### `__init__.py`
Package initialization. Exports `TypeChecker` and data classes for external use:
```python
from typechecker import TypeChecker, VariableInfo, Scope
```

### `core.py`
Main `TypeChecker` class with:
- **Data classes**: `VariableInfo`, `Scope`
- **State initialization**: Scope management, error reporter
- **`check(program)`**: Main entry point for checking a single-file program
- **`check_module(program, namespace)`**: Entry point for checking a module with namespace

#### Key Data Classes
| Class | Purpose |
|-------|---------|
| `VariableInfo` | Variable type, mutability, and location |
| `Scope` | Lexical scope with variable bindings and parent chain |

#### Key State Variables
| Variable | Type | Purpose |
|----------|------|---------|
| `self.namespace` | `Namespace` | Symbol namespace for all types, aliases, conformances, and type assignments |
| `self.current_scope` | `Scope` | Current lexical scope |
| `self.current_function` | `Function` | Function being checked |
| `self.current_method` | `Method` | Method being checked |
| `self.loop_depth` | `int` | Loop nesting depth (for break/continue) |

### `types.py`
Type resolution, compatibility checking, and resource trait detection.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `get_struct_info(name)` | Lookup StructSymbol from namespace |
| `get_enum_info(name)` | Lookup EnumSymbol from namespace |
| `get_trait_info(name)` | Lookup TraitSymbol from namespace |
| `get_function_info(name)` | Lookup FunctionSymbol from namespace |
| `_resolve_type_alias(saw_type)` | Resolve type aliases to their definitions |
| `_resolve_type(saw_type)` | Resolve user types (enums parsed as structs) |
| `_get_underlying_type(saw_type)` | Get underlying primitive for distinct types |
| `_types_compatible(expected, actual)` | Check if types are compatible |
| `_is_no_copy_type(saw_type)` | Check if type implements NoCopy |
| `_is_implicit_copy_type(saw_type)` | Check if type implements ImplicitCopy |
| `_is_explicit_copy_type(saw_type)` | Check if type implements ExplicitCopy |
| `_is_deinit_type(saw_type)` | Check if type implements Deinit |
| `_check_operand_agreement(left, right, ...)` | **The single operand-agreement checkpoint (design 195 rule 1).** All typed operands of an operation have the SAME type; implicit promotion happens from bare integer literals and nowhere else. Its docstring NAMES its six entry points (arithmetic, `%`, the wrapping trio, the bitwise `& \| ^`, the comparisons, compound assignment, range bounds) and the one deliberate non-entry (the shifts, whose right operand is a count rather than a peer). |
| `_adopt_bare_literal_operand(expr, l, r)` | The carve-out applied: a bare integer literal operand adopts the other operand's type through `_apply_literal_expected_type`, so it is range-checked at the literal, materialized at the adopted width, and reached through a leading `-`. |
| `_check_value_transfer(expr, target, ...)` | **The single value-transfer checkpoint.** Every copy/move site (let/var, assignment RHS, call args, returns, struct fields, array/tuple/enum payloads) funnels through here: enforces `NoCopy`/`ExplicitCopy` move-discipline and marks `ImplicitCopy` sites so codegen inserts `copy()`. (Use-after-move dataflow beyond let/var is a documented gap.) |
| `_check_call_exclusivity(values, ...)` | **The single Law-of-Exclusivity checkpoint for a call.** A `&var` (or `&var self` receiver) path must be disjoint from every other by-reference/moved path in the same call; by-value args are snapshots and not collected. The access set holds the receiver, the `&`/`&var` arguments, the `move`s, an `o.take()` receiver, a closure argument's borrow captures, and — since design 199 — every `&`/`&var` a NESTED call in the argument list creates, because an argument's borrow extends over the whole call expression. Its docstring NAMES its fifteen entry points in `expressions.py`. |
| `_check_copy_trait_exclusivity()` | Enforce that a type does not declare both `ImplicitCopy` and `ExplicitCopy` |
| `_build_access_path(expr)` | Build the root+projection access path used by the exclusivity check |
| `_check_no_copy_return(expr, type)` | Validate NoCopy types are moved on return |
| `_check_integer_literal_range(value, type)` | Validate integer fits target type |
| `_check_no_copy_containment(struct)` | Check NoCopy field containment rules |
| `_check_implicit_copy_containment(struct)` | Check ImplicitCopy field containment rules |
| `_check_explicit_copy_containment(struct)` | Check ExplicitCopy field containment rules |
| `_check_deinit_containment(struct)` | Check Deinit field containment rules |

### `registration.py`
Type and symbol registration during the first pass of type checking.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_register_builtins()` | Register built-in functions and types |
| `_register_type_definition(type_def)` | Register a type alias |
| `_register_struct(struct)` | Register a struct definition |
| `_register_enum(enum)` | Register an enum definition |
| `_register_trait(trait)` | Register a trait definition |
| `_register_function(func)` | Register a function signature |
| `_register_extern_function(func)` | Register an external (FFI) function |
| `_register_extension(ext)` | Register methods from an extension |
| `_check_trait_conformance(type, trait)` | Verify type implements trait |
| `_types_compatible_for_trait(expected, actual)` | Trait type compatibility |
| `_resolve_trait_type(type, self_type)` | Resolve Self and associated types |
| `_block_has_early_exit(block)` | Check if block definitely exits early |

### `statements.py`
Statement checking including variable bindings, assignments, and control flow.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_check_extension(ext)` | Type check all methods in an extension |
| `_check_method(struct, method)` | Type check a method body |
| `_check_function(func)` | Type check a function body |
| `_check_block(block)` | Check a block and return its type |
| `_check_statement(stmt)` | Statement dispatch |
| `_check_let_statement(stmt)` | Check let/var variable binding |
| `_check_guard_let_statement(stmt)` | Check guard let/var for optionals |
| `_check_assign_statement(stmt)` | Check assignment statement |
| `_check_return_statement(stmt)` | Check return statement |
| `_check_while_expr(expr)` | Check while loop as statement |
| `_check_while_expr_as_expression(expr)` | Check while loop as expression |
| `_check_for_loop(expr)` | Check for loop as statement |
| `_check_for_loop_as_expression(expr)` | Check for loop as expression |
| `_get_iterator_item_type(type)` | Get Item type for Iterator implementors |
| `_check_range_expr(expr)` | Check range expression (start..end) |
| `_check_break_statement(stmt)` | Check break statement |
| `_check_continue_statement(stmt)` | Check continue statement |

### `expressions.py`
Expression type checking using a visitor pattern.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `_check_expression(expr)` | Main dispatch using visitor pattern |
| `visit_IntLiteral(expr)` | Return Int type |
| `visit_StringLiteral(expr)` | Return String type |
| `visit_Identifier(expr)` | Look up variable in scope |
| `visit_BinaryOp(expr)` | Check binary operators |
| `visit_UnaryOp(expr)` | Check unary operators |
| `visit_FunctionCall(expr)` | Check function call arguments |
| `visit_MethodCall(expr)` | Check method call on object |
| `visit_StructInit(expr)` | Check struct field initialization |
| `visit_EnumInit(expr)` | Check enum variant initialization |
| `visit_MatchExpr(expr)` | Check match expression exhaustiveness |
| `visit_IfExpr(expr)` | Check if expression branches |
| `visit_IfLetExpr(expr)` | Check if-let optional binding |
| `visit_ClosureExpr(expr)` | Check closure expression |
| `visit_MoveExpr(expr)` | Check move expression |
| `visit_CastExpr(expr)` | Check type cast |
| `visit_ForceUnwrap(expr)` | Check force unwrap (!) |
| `visit_NilCoalesce(expr)` | Check nil coalescing (??) |
| `visit_OptionalChain(expr)` | Check optional chaining (?.) |

#### Expression Visitor Pattern
```python
def _check_expression(self, expr):
    method_name = f'visit_{expr.__class__.__name__}'
    visitor = getattr(self, method_name, None)
    if visitor:
        return visitor(expr)
    return None
```

## Type Checking Phases

### Phase 1: Registration
1. Register built-in types and functions
2. Register all type definitions (type aliases)
3. Register all struct definitions
4. Register all enum definitions
5. Register all trait definitions
6. Register all function signatures
7. Register all extension methods

### Phase 2: Validation
1. Check trait conformance for extensions
2. Check `ImplicitCopy`/`ExplicitCopy` mutual exclusivity
3. Check containment rules (NoCopy, ImplicitCopy, ExplicitCopy, Deinit)
4. Check function bodies (generic bodies are checked once, abstractly, against
   their bounds — with return-type reconciliation and bound-aware method
   resolution deferred to instantiation)
5. Check method bodies in extensions
6. Throughout body checking, every copy/move funnels through the value-transfer
   checkpoint, and every call's by-reference args are checked for exclusivity

## Adding New Features

When adding new type checking features:

1. **Identify the category** - Which mixin does it belong to?
2. **Add the method** - Implement in the appropriate mixin file
3. **Add visitor if needed** - If it's a new expression type, add `visit_*` in `expressions.py`
4. **Update this documentation** - Add method to the appropriate table
5. **Run tests** - Ensure all tests pass

## Testing

```bash
make test           # Run all tests
make test-verbose   # Run with verbose output
make test-filter FILTER=type  # Run tests matching pattern
```
