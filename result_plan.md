# Implementation Plan: Result<T, E> and try/try?/try! Syntax

## Status

### Completed
- [x] Phase 1: Lexer - TRY, CATCH tokens
- [x] Phase 2: AST Nodes - TryExpr, TryCatchExpr, Result helpers on SawType
- [x] Phase 3: Parser - try expression parsing
- [x] Phase 4: Type Checker - Result enum registration, Error trait, auto-wrap detection
- [x] Phase 5: Code Generator - ResultsMixin, auto-wrap codegen for returns
- [x] Phase 6: Testing - result_basic.saw, result_same_type.saw

### Remaining
- [ ] `try expr` codegen (error propagation to caller)
- [ ] `try? expr` codegen (convert Result to Optional)
- [ ] `try! expr` codegen (force unwrap with panic)
- [ ] `try { } catch { }` block syntax codegen
- [ ] Inline `catch` block codegen

---

## Overview

Add `Result<T, E>` as a built-in generic enum and implement `try` expression family with `catch` syntax for error handling.

## Design Summary

### Result Type
```saw
enum Result<T, E> {
    case Ok(value: T),
    case Err(error: E)
}
```
- Built-in generic enum (compiler-recognized like Optional)
- LLVM: Tagged union `{ i32, [max_bytes x i8] }` (Ok=0, Err=1)

### Try Syntax Variants
| Syntax | Behavior | Return Type |
|--------|----------|-------------|
| `try expr` | Unwraps Ok, propagates Err | `T` |
| `try? expr` | Unwraps Ok, returns None on Err | `T?` |
| `try! expr` | Unwraps Ok, panics on Err | `T` |

### Catch Syntax
```saw
// Inline catch - handles error locally
let x = try riskyOp() catch { fallback }

// Block catch - catches unhandled errors from the block
try {
    let a = try op1()
    let b = try op2()
} catch {
    print("Error: {error.message()}")
}

// Mixed: inline catches work inside try blocks
try {
    let a = try op1() catch { default1 }  // Handled locally
    let b = try op2()                      // Propagates to outer catch
    let c = try op3() catch { default3 }  // Handled locally
} catch {
    // Only catches errors from op2 (and any not caught inline)
}
```
- Implicit `error` variable in catch block
- Inline catches take precedence (local handling)
- Unhandled `try` expressions propagate to enclosing try-catch or function return

### Error Trait
```saw
trait Error {
    func message(self) -> String
}
```
- Error types must conform to `Error` for propagation

### Auto-Wrapping Returns (Ergonomic Feature)

In functions returning `Result<T, E>`, return values are auto-wrapped:

```saw
func parseInt(s: String) -> Result<Int, ParseError> {
    if valid {
        return 42  // Auto-wraps to Result<Int, ParseError>.Ok(value: 42)
    }
    return ParseError(message: "invalid")  // Auto-wraps to Result<..>.Err(error: ...)
}
```

**Rules**:
1. If return type is `Result<T, E>` and value type is `T` → wrap in `Ok`
2. If return type is `Result<T, E>` and value type is `E` (or conforms to Error) → wrap in `Err`
3. If value is already `Result<T, E>` → no wrapping
4. Similar to how `None` is auto-typed in optional-returning functions

---

## Implementation Phases

### Phase 1: Lexer
**File**: `sawc/lexer.py`
- Add `TRY` and `CATCH` to `TokenType` enum
- Add to `KEYWORDS` dict

### Phase 2: AST Nodes
**File**: `sawc/ast_nodes.py`

Add nodes:
```python
@dataclass
class TryExpr(Expression):
    expr: Expression
    variant: str  # "propagate", "optional", "force"
    line: int = 0
    column: int = 0

@dataclass
class TryCatchExpr(Expression):
    try_block: Block
    catch_block: Block
    error_binding: Optional[str] = None  # default: "error"
    line: int = 0
    column: int = 0
```

Add helper methods to `SawType`:
- `is_result() -> bool`
- `unwrap_result_ok() -> SawType`
- `unwrap_result_err() -> SawType`

### Phase 3: Parser
**File**: `sawc/parser/expressions.py`

Add `parse_try_expression()`:
1. Consume `try` token
2. Check for `?` (optional) or `!` (force) modifier
3. If `{` follows → parse try-catch block
4. Otherwise parse expression
5. Check for `catch` keyword → parse catch block

Update `parse_primary()` to handle `TRY` token.

**File**: `sawc/parser/statements.py`
- Handle try-catch as statement context

### Phase 4: Type Checker
**File**: `sawc/typechecker/core.py`

Register built-ins:
```python
# Result<T, E> enum
self.enums["Result"] = EnumInfo(
    name="Result",
    variants={
        "Ok": [("value", T)],
        "Err": [("error", E)]
    },
    type_params=[T, E]
)

# Error trait
self.traits["Error"] = TraitInfo(
    name="Error",
    methods={"message": (self) -> String}
)
```

**File**: `sawc/typechecker/expressions.py`

Add `_check_try_expr()`:
1. Check inner expr is `Result<T, E>`
2. For `try?`: return `T?`
3. For `try!`: return `T`
4. For `try`: validate function returns `Result<_, E>`, return `T`

Add `_check_try_catch_expr()`:
1. Check try block
2. Create scope with `error` binding for catch block
3. Check catch block
4. Validate try/catch return types compatible

**File**: `sawc/typechecker/statements.py`

Update `_check_return_statement()` for auto-wrapping:
```python
def _check_return_statement(self, stmt):
    expected = self.current_return_type
    actual = self._check_expression(stmt.value)

    if expected.is_result():
        ok_type = expected.unwrap_result_ok()
        err_type = expected.unwrap_result_err()

        # Already a Result - no wrapping
        if actual.is_result():
            # Normal type check
            pass
        # Value matches T - auto-wrap in Ok
        elif self._types_compatible(actual, ok_type):
            stmt.auto_wrap = "ok"  # Flag for codegen
        # Value matches E - auto-wrap in Err
        elif self._types_compatible(actual, err_type):
            stmt.auto_wrap = "err"
        else:
            self.reporter.error(...)
```

### Phase 5: Code Generator
**New File**: `sawc/codegen/results.py`

Create `ResultsMixin` class with:

`_generate_try_expr()`:
- Extract tag from Result
- Branch on is_ok

`_generate_try_force()`:
- Ok branch: extract value, continue
- Err branch: print panic message, call abort()

`_generate_try_optional()`:
- Ok branch: wrap value in Some
- Err branch: create None
- Merge with phi node

`_generate_try_propagate()`:
- Ok branch: extract value, continue
- Err branch: wrap error in Result.Err, cleanup scopes, return

`_generate_try_catch_expr()`:
- Set catch_destination for nested try expressions
- Generate try block
- Generate catch block with error binding
- Merge results

**File**: `sawc/codegen/core.py`
- Import and inherit `ResultsMixin`
- Add visitor methods for TryExpr, TryCatchExpr

**File**: `sawc/codegen/statements.py`

Update `_generate_return_statement()` for auto-wrapping:
```python
def _generate_return_statement(self, stmt):
    value = self._generate_expression(stmt.value)

    if hasattr(stmt, 'auto_wrap') and stmt.auto_wrap:
        if stmt.auto_wrap == "ok":
            value = self._create_result_ok(value, self.current_return_type)
        elif stmt.auto_wrap == "err":
            value = self._create_result_err(value, self.current_return_type)

    self._generate_scope_cleanup()
    self.builder.ret(value)
```

### Phase 6: Testing

Create test files:
- `examples/result_basic.saw` - Result creation and matching
- `examples/result_auto_wrap.saw` - Auto-wrapping returns in Result functions
- `examples/try_force.saw` - try! panics on Err
- `examples/try_optional.saw` - try? returns T?
- `examples/try_propagate.saw` - try propagates to caller
- `examples/try_catch_inline.saw` - inline catch syntax
- `examples/try_catch_block.saw` - block catch syntax
- `examples/error_trait.saw` - Error trait conformance

---

## File Summary

### Modify
| File | Changes |
|------|---------|
| `sawc/lexer.py` | Add TRY, CATCH tokens |
| `sawc/ast_nodes.py` | Add TryExpr, TryCatchExpr; Result helpers on SawType; auto_wrap field on ReturnStatement |
| `sawc/parser/expressions.py` | Add parse_try_expression() |
| `sawc/parser/statements.py` | Handle try-catch statements |
| `sawc/typechecker/core.py` | Register Result enum, Error trait |
| `sawc/typechecker/expressions.py` | Add try expression type checking |
| `sawc/typechecker/statements.py` | Auto-wrap detection in return statements |
| `sawc/codegen/core.py` | Add visitor methods, import ResultsMixin |
| `sawc/codegen/statements.py` | Generate auto-wrap code for returns |

### Create
| File | Purpose |
|------|---------|
| `sawc/codegen/results.py` | ResultsMixin for try/Result codegen |

---

## Example Usage

```saw
struct IoError {
    msg: String
}

extension IoError: Error {
    func message(self) -> String {
        self.msg
    }
}

// Auto-wrapping: return String → Ok, return IoError → Err
func readFile(path: String) -> Result<String, IoError> {
    if File.exists(path) {
        return "file contents"  // Auto-wrapped to Ok
    }
    return IoError(msg: "not found")  // Auto-wrapped to Err
}

// Propagation with try + auto-wrap return
func processFile(path: String) -> Result<Int, IoError> {
    let content = try readFile(path)  // Propagates Err
    return content.len()  // Auto-wrapped to Ok
}

// Convert to optional
func maybeRead(path: String) -> String? {
    try? readFile(path)
}

// Force unwrap (panics on error)
func mustRead(path: String) -> String {
    try! readFile(path)
}

// Inline catch
let content = try readFile("data.txt") catch {
    "default content"
}

// Block catch
try {
    let a = try readFile("a.txt")
    let b = try readFile("b.txt")
    print("{a} {b}")
} catch {
    print("Error: {error.message()}")
}
```
