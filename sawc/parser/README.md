# Parser Module

**IMPORTANT: This documentation must be kept in sync with the code. Any changes to the parser module should be reflected here.**

## Overview

The `parser` module is a recursive descent parser that transforms tokens from the lexer into an Abstract Syntax Tree (AST). It handles Saw's expression-oriented syntax, including operator precedence, control flow, closures, and module declarations. The implementation uses a mixin-based architecture where the main `Parser` class inherits from multiple focused mixin classes.

## Architecture

```
Parser (core.py)
    ├── ExpressionsMixin (expressions.py)
    ├── StatementsMixin (statements.py)
    ├── DeclarationsMixin (declarations.py)
    └── TypeParsingMixin (types.py)
```

All mixins share state through `self` - they access `self.tokens`, `self.pos`, `self.allow_trailing_closure`, etc. defined in `core.py`.

## File Descriptions

### `__init__.py`
Package initialization. Exports `Parser` for external use:
```python
from parser import Parser
```

### `core.py` (447 lines)
Main `Parser` class with:
- **State management**: Token stream, position, trailing closure flag
- **Core utilities**: `current()`, `peek()`, `advance()`, `match()`, `expect()`
- **`parse()`**: Main entry point, returns `Program` AST
- **Module parsing**: `parse_import()`, `parse_export()`, `parse_module_decl()`
- **Type parameters**: `parse_type_params()`, `_parse_single_type_param()`
- **Visibility**: `_parse_visibility()`

#### Key State Variables
| Variable | Type | Purpose |
|----------|------|---------|
| `self.tokens` | `List[Token]` | Token stream from lexer |
| `self.pos` | `int` | Current position in token stream |
| `self.allow_trailing_closure` | `bool` | Whether trailing closures are allowed (disabled in conditions) |

#### Core Utility Methods
| Method | Purpose |
|--------|---------|
| `current()` | Get current token |
| `peek(offset)` | Look ahead in token stream |
| `advance()` | Consume and return current token |
| `match(*types)` | Check if current token matches any type |
| `expect(type, msg)` | Consume expected token or error |
| `skip_newlines()` | Skip newline tokens |
| `match_ident(value)` | Check for context-sensitive keyword |
| `expect_ident(value)` | Expect context-sensitive keyword |
| `error(msg)` | Raise syntax error with location |

### `types.py` (146 lines)
Type annotation parsing.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `parse_type()` | Parse a type annotation with optional suffix (?) |
| `_parse_base_type()` | Parse non-optional base type |
| `_parse_type_args()` | Parse type arguments: `<Int, String>` |

#### Supported Types
- Primitive: `Int`, `Float`, `Bool`, `String`
- Fixed-width integers: `Int8`, `Int16`, `Int32`, `Int64`, `UInt8`, etc.
- Array: `[Type; Size]`
- Tuple: `(Type, Type, ...)`
- Function: `(Type, Type) -> ReturnType`
- Optional: `Type?`
- Generic: `Box<T>`, `Map<K, V>`
- Pointer: `UnsafePointer<T>`, `UnsafeConstPointer<T>`
- Self: `Self` (in trait methods)

### `declarations.py` (532 lines)
Top-level declaration parsing.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `parse_function(visibility)` | Parse function declaration |
| `parse_struct(visibility)` | Parse struct declaration with fields |
| `parse_enum(visibility)` | Parse enum with variants |
| `parse_trait(visibility)` | Parse trait with methods |
| `parse_extension(visibility)` | Parse extension block |
| `parse_type_definition(visibility)` | Parse type alias |
| `parse_extern_block()` | Parse extern block with FFI functions |
| `parse_parameters()` | Parse parameter list with types |
| `_parse_method()` | Parse method in extension |
| `_parse_trait_method()` | Parse method signature in trait |
| `_parse_extern_function()` | Parse extern function declaration |

### `statements.py` (241 lines)
Statement and block parsing.

#### Key Methods
| Method | Purpose |
|--------|---------|
| `parse_block()` | Parse `{ statements }` block |
| `parse_statement()` | Statement dispatch |
| `parse_let_statement(mutable)` | Parse let/var binding |
| `parse_guard_statement()` | Parse guard let/var |
| `parse_return_statement()` | Parse return statement |
| `parse_while_statement()` | Parse while loop |
| `parse_for_statement()` | Parse for loop |
| `parse_break_statement()` | Parse break (with optional value) |
| `parse_continue_statement()` | Parse continue |
| `parse_assignment_or_expression_statement()` | Parse assignment or expression |

### `expressions.py` (954 lines)
Expression parsing with operator precedence.

#### Operator Precedence (lowest to highest)
1. Nil coalesce: `??`
2. Logical OR: `||`
3. Logical AND: `&&`
4. Comparison: `==`, `!=`, `<`, `>`, `<=`, `>=`
5. Range: `..`
6. Additive: `+`, `-`
7. Multiplicative: `*`, `/`, `%`
8. Unary: `-`, `not`, `move`
9. Cast: `as`
10. Postfix: `.`, `!`, `?.`, `[]`
11. Primary: literals, identifiers, calls

#### Key Methods
| Method | Purpose |
|--------|---------|
| `parse_expression()` | Entry point (starts with nil coalesce) |
| `parse_nil_coalesce()` | Parse `expr ?? default` |
| `parse_or()` | Parse `expr \|\| expr` |
| `parse_and()` | Parse `expr && expr` |
| `parse_comparison()` | Parse comparison operators |
| `parse_range()` | Parse `start..end` |
| `parse_additive()` | Parse `+`, `-` |
| `parse_multiplicative()` | Parse `*`, `/`, `%` |
| `parse_unary()` | Parse `-`, `not`, `move` |
| `parse_cast()` | Parse `expr as Type` |
| `parse_postfix()` | Parse `.`, `!`, `?.`, `[]` |
| `parse_primary()` | Parse literals, identifiers, calls |
| `parse_arguments()` | Parse argument list |
| `parse_function_call(token, type_args)` | Parse function call |
| `parse_struct_init(token, type_args)` | Parse struct initialization |
| `parse_if_expression()` | Parse if/if-let expression |
| `parse_match_expression()` | Parse match expression |
| `_parse_closure_expression()` | Parse closure `{ x in ... }` |
| `_is_closure_with_named_params()` | Detect named param closure |
| `_parse_closure_params()` | Parse closure parameters |
| `_parse_closure_body()` | Parse closure body |
| `_parse_interpolated_string(raw, line, col)` | Parse string interpolation |
| `_count_shorthand_params(body)` | Count `$0`, `$1`, etc. usage |

#### Trailing Closure Handling
The parser tracks `allow_trailing_closure` to handle ambiguity:
- Disabled in `if`, `while`, `guard`, `for`, `match` conditions
- Enabled for function calls: `foo(x) { closure }`
- Enabled for method calls: `obj.method { closure }`

## Parse Tree to AST

The parser produces AST nodes defined in `ast_nodes.py`. Key node types:

### Program Structure
- `Program`: Top-level container
- `Function`, `Struct`, `Enum`, `Trait`, `Extension`
- `ImportDecl`, `ExportDecl`, `ModuleDecl`

### Statements
- `LetStatement`, `AssignStatement`, `ReturnStatement`
- `GuardLetStatement`, `ExpressionStatement`
- `WhileExpr`, `ForLoop`, `BreakStatement`, `ContinueStatement`

### Expressions
- Literals: `IntLiteral`, `FloatLiteral`, `BoolLiteral`, `StringLiteral`
- Operations: `BinaryOp`, `UnaryOp`, `CastExpr`
- Access: `Identifier`, `MemberAccess`, `ArrayIndex`, `TupleIndex`
- Calls: `FunctionCall`, `MethodCall`, `StructInit`, `EnumInit`
- Control: `IfExpr`, `IfLetExpr`, `MatchExpr`
- Optionals: `NoneLiteral`, `ForceUnwrap`, `NilCoalesce`, `OptionalChain`
- Closures: `ClosureExpr`

## Adding New Features

When adding new parsing features:

1. **Identify the category** - Which mixin does it belong to?
2. **Add the method** - Implement in the appropriate mixin file
3. **Update precedence if needed** - For new operators, add to the chain
4. **Update this documentation** - Add method to the appropriate table
5. **Run tests** - Ensure all tests pass

## Testing

```bash
make test           # Run all tests
make test-verbose   # Run with verbose output
make test-filter FILTER=parse  # Run tests matching pattern
```
