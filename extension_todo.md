# Struct Extensions Implementation TODO

## Status Overview
- **Phase 1: Basic Methods** - ✅ COMPLETE
- **Phase 2: Custom Init Methods** - ✅ COMPLETE
- **Phase 3: Advanced Features** - 📋 PLANNED

---

## Phase 1: Basic Methods (COMPLETE)

### ✅ Lexer Changes
- [x] Add `INIT` token to TokenType enum (line 33)
- [x] Add `'init': TokenType.INIT` to KEYWORDS dict (line 95)

### ✅ AST Nodes
- [x] Add `Extension` node for extension declarations
- [x] Add `Method` node for method definitions
- [x] Add `MethodCall` expression node
- [x] Add `SelfExpr` expression node for `self` keyword
- [x] Update `Program` node to include `extensions` list

### ✅ Parser Changes
- [x] Update `parse()` to handle `EXTENSION` token
- [x] Implement `parse_extension()` method
- [x] Implement `parse_method()` method
- [x] Update `parse_parameters()` to handle `self` without type annotation
  - Parser creates VOID placeholder for self type
  - Type checker fills in actual struct type during registration
- [x] Update `parse_postfix()` to distinguish method calls from field access
  - Check for `(` after identifier to determine if method call
- [x] Update `parse_primary()` to handle `self` keyword

### ✅ Type Checker Changes
- [x] Extend `StructInfo` to include `methods` dict
- [x] Add `MethodInfo` dataclass for method metadata
- [x] Add `current_method` tracking field to TypeChecker
- [x] Implement `_register_extension()` method
  - Verify struct exists
  - Check for duplicate methods
  - Validate first parameter is named "self"
  - Infer self type from extension target struct
- [x] Implement `_check_extension()` and `_check_method()` methods
- [x] Implement `_check_method_call()` method
  - Verify object is struct type
  - Look up method in struct's methods
  - Validate argument count and types
- [x] Implement `_check_self_expr()` method
- [x] Update `_check_member_access()` to distinguish methods from fields

### ✅ Code Generator Changes
- [x] Implement method name mangling: `StructName_methodName`
- [x] Implement `_declare_extension_methods()` method
- [x] Implement `_generate_extension_methods()` and `_generate_method()` methods
- [x] Implement `_generate_method_call()` method
  - Pass self as first argument
  - Call mangled method function
- [x] Implement `_generate_self_expr()` method
- [x] Update `_generate_expression()` to handle new node types

### ✅ Testing
- [x] Create `examples/extension_simple.saw` test case
- [x] Verify compilation succeeds
- [x] Verify execution produces correct output (7)

---

## Phase 2: Custom Init Methods (COMPLETE)

### ✅ Type Checker Enhancements
- [x] Update `_register_extension()` to handle init methods
  - Multiple init methods supported with different parameter signatures
  - Parameter names used as keys to distinguish init methods
  - Check parameter names don't conflict with field names (ambiguity check)
  - Store init signatures in struct info
- [x] Update `_check_struct_init()` for parameter-based resolution
  - Match parameter names to field names (field init)
  - Match parameter names to custom init signatures
  - Validate argument types match chosen init
  - Error if ambiguous (matches both field init and custom init)
  - Store resolution in `expr.resolved_init_params`

### ✅ Code Generator Enhancements
- [x] Implement `_generate_init_method()` for custom inits
  - Generate LLVM function for init method
  - Init method body returns struct value
  - Handle parameter initialization
- [x] Update `_generate_struct_init()` to handle custom inits
  - Check if custom init call via `resolved_init_params`
  - If custom init: Generate call to mangled init method
  - If field init: Use existing field-by-field construction
- [x] Update method name mangling to support init overloading
  - Format: `StructName_init_param1_param2_param3`
  - Prevents name collisions for multiple init methods

### ✅ Testing
- [x] Create `examples/extension_init.saw` test case
- [x] Test field init vs custom init resolution
- [x] Test multiple custom inits with different parameter sets
- [x] Verify compilation and execution (output: 3 4 5 5 5 5)

---

## Phase 3: Advanced Features (PLANNED)

### 📋 Mutable Self (`var self`)
- [ ] Update parser to detect `var` before `self` parameter
- [ ] Track mutability in `MethodInfo`
- [ ] Update code generator to handle mutable self
- [ ] Create test cases for mutable methods

### 📋 Built-in Type Extensions
- [ ] Design approach for extending Int, String, Bool, etc.
- [ ] Update type system to support built-in type extensions
- [ ] Implement registration for built-in type methods
- [ ] Create test cases

### 📋 Error Handling Improvements
- [ ] Better error messages for:
  - Extension of undefined struct
  - Duplicate method names
  - Missing self parameter
  - Self type mismatch
  - Method call on non-struct type
  - Accessing method as field

---

## Design Decisions Made

### Init Resolution Strategy
- **Decision**: Use parameter names to distinguish field init from custom init
- **Rationale**:
  - `Point(x: 10, y: 20)` matches field names → field init
  - `Point(r: 5.0, theta: 3.14)` matches init parameters → custom init
  - Unambiguous and natural syntax
- **Syntax**: `init(param1: Type, param2: Type)` (no custom name needed)

### Self Parameter Type Inference
- **Decision**: Don't require type annotation for self parameter
- **Rationale**: Type is always implicitly the struct being extended
- **Implementation**:
  - Parser creates VOID placeholder
  - Type checker fills in actual struct type during registration

### Method Name Mangling
- **Decision**: Use `StructName_methodName` format
- **Rationale**: Simple, predictable, avoids conflicts

### Method Dispatch
- **Decision**: Pass self as first argument to mangled function
- **Rationale**: Simple implementation, matches C++ implicit `this`

---

## Known Issues / Future Improvements

1. **No static methods**: All methods currently require self parameter
2. **No method overloading**: Method names must be unique per struct
3. **No generic methods**: Methods cannot have type parameters yet
4. **No trait methods**: Extensions don't implement traits (traits not implemented)
5. **Return type required**: Even void methods need explicit `-> Void` (not a big issue)

---

## File Change Summary

### Modified Files
1. `sawc/lexer.py` - Added INIT token
2. `sawc/ast_nodes.py` - Added 4 new node types, updated Program
3. `sawc/parser.py` - Added extension/method parsing, self inference
4. `sawc/typechecker.py` - Added extension validation, method checking
5. `sawc/codegen.py` - Added method code generation

### New Files
1. `examples/extension_simple.saw` - Basic method test case
2. `.build/extension_simple` - Compiled test binary

---

## Testing Evidence

### Successful Test Run
```bash
$ python3 sawc/sawc.py examples/extension_simple.saw
$ ./.build/extension_simple
7
```

### Test Case Code
```saw
struct Point {
    x: Int
    y: Int
}

extension Point {
    func distance(self) -> Int {
        self.x + self.y
    }
}

func main() {
    let p = Point(x: 3, y: 4)
    let d = p.distance()
    print(d)
}
```

**Expected Output**: `7` (3 + 4)
**Actual Output**: `7` ✅

### Phase 2 Test Case

```bash
$ ./sawc/sawc.py examples/extension_init.saw
$ ./.build/extension_init
3
4
5
5
5
5
```

**Test Case Code**:
```saw
struct Point {
    x: Int
    y: Int
}

extension Point {
    // Custom init with magnitude parameter
    init(magnitude: Int) -> Point {
        Point(x: magnitude, y: magnitude)
    }

    // Custom init with a, b parameters
    init(a: Int, b: Int) -> Point {
        let sum = a + b
        Point(x: sum, y: sum)
    }
}

func main() {
    // Field initialization
    let p1 = Point(x: 3, y: 4)
    print(p1.x)  // 3
    print(p1.y)  // 4

    // Custom init with magnitude
    let p2 = Point(magnitude: 5)
    print(p2.x)  // 5
    print(p2.y)  // 5

    // Custom init with a, b
    let p3 = Point(a: 2, b: 3)
    print(p3.x)  // 5 (2 + 3)
    print(p3.y)  // 5 (2 + 3)
}
```

**Expected Output**: `3 4 5 5 5 5`
**Actual Output**: `3 4 5 5 5 5` ✅

---

## Notes

- Phase 1 implementation is complete and verified working
- Phase 2 implementation is complete and verified working
- Multiple init methods can now be defined with different parameter signatures
- Parameter-based resolution distinguishes field init from custom inits
- All completed work has been tested end-to-end
- Binary files successfully compiled and executed correctly
