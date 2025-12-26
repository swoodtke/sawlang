# For Loops Implementation Plan

This document outlines the implementation plan for adding for loops to Saw, which requires first implementing generics and interfaces.

## Overview

**Goal**: Implement `for item in collection { ... }` loops using a proper Iterator interface.

**Dependencies** (in order):
1. Basic Generics
2. Interfaces
3. Interface Bounds
4. Associated Types
5. Iterator/Iterable Interfaces
6. Range Types
7. For Loop Syntax

---

## Phase 1: Basic Generics

### 1.1 Syntax Design

```saw
// Generic functions
func identity<T>(x: T) -> T {
    x
}

func swap<T>(a: T, b: T) -> (T, T) {
    (b, a)
}

// Generic structs
struct Box<T> {
    value: T
}

struct Pair<A, B> {
    first: A
    second: B
}

// Generic enums (already have syntax, need to make it work)
enum Option<T> {
    Some(T)
    None
}

enum Result<T, E> {
    Ok(T)
    Err(E)
}
```

### 1.2 Lexer Changes

No new tokens needed - we already have:
- `<` (LT) and `>` (GT) for comparison
- These can be reused for type parameters based on context

### 1.3 Parser Changes

**New AST nodes**:
```python
@dataclass
class TypeParameter:
    name: str
    bounds: List[str] = field(default_factory=list)  # For Phase 3
    line: int = 0
    column: int = 0

# Update existing nodes to include type parameters:
# - Function: add type_params: List[TypeParameter]
# - Struct: add type_params: List[TypeParameter]
# - Enum: add type_params: List[TypeParameter]
```

**Parsing type parameters**:
```
parse_type_params() -> List[TypeParameter]:
    if not match('<'): return []
    params = []
    params.append(parse_type_param())
    while match(','):
        params.append(parse_type_param())
    expect('>')
    return params
```

**Update SawType for generic instantiation**:
```python
@dataclass
class SawType:
    kind: TypeKind
    # ... existing fields ...
    type_args: List[SawType] = None  # For Box<Int>, Option<String>, etc.
```

### 1.4 Type Checker Changes

**Type parameter scoping**:
- When checking a generic function/struct, add type parameters to scope
- Type parameters are treated as abstract types during checking

**Type instantiation**:
- When a generic is used with concrete types, substitute type parameters
- `Box<Int>` → substitute T=Int throughout

**Type inference** (basic):
- Infer type arguments from usage when possible
- `let b = Box(value: 42)` → infer `Box<Int>`

### 1.5 Codegen Changes

**Monomorphization**:
- Generate specialized versions for each type instantiation
- `identity<Int>` and `identity<String>` become separate functions
- Track which instantiations are used

**Name mangling**:
- `identity<Int>` → `identity$Int`
- `Box<Int>` → `Box$Int`

### 1.6 Implementation Steps

1. [x] Add `TypeParameter` AST node
2. [x] Update `Function` AST to include `type_params`
3. [x] Update parser to parse `<T, U>` after function name
4. [x] Update type checker to handle type parameters in scope
5. [x] Add basic type substitution logic
6. [ ] Update `Struct` AST and parser for generic structs
7. [ ] Update `Enum` AST and parser for generic enums
8. [x] Implement monomorphization in codegen
9. [x] Add tests for generic functions
10. [ ] Add tests for generic structs
11. [ ] Add tests for generic enums

**Status**: Generic functions complete (commit 185b27d). Generic structs/enums deferred as not strictly required for for-loops.

---

## Phase 2: Interfaces

### 2.1 Syntax Design

```saw
// Interface definition
interface Display {
    func display(self) -> String
}

interface Clone {
    func clone(self) -> Self
}

// Interface implementation via extension
extension Int: Display {
    func display(self) -> String {
        // ... convert to string
    }
}

extension Point: Display, Clone {
    func display(self) -> String {
        // ...
    }

    func clone(self) -> Point {
        Point(x: self.x, y: self.y)
    }
}

// Default implementations in interfaces
interface Greet {
    func name(self) -> String

    func greet(self) -> String {
        "Hello, " + self.name() + "!"
    }
}
```

### 2.2 Lexer Changes

Add new keyword:
- `INTERFACE` for `interface`

Note: We reuse `extension` with `: InterfaceName` syntax for implementations.

### 2.3 Parser Changes

**New AST nodes**:
```python
@dataclass
class Interface:
    name: str
    type_params: List[TypeParameter]
    methods: List[InterfaceMethod]  # Required methods
    default_methods: List[Method]  # Methods with default implementation
    line: int = 0
    column: int = 0

@dataclass
class InterfaceMethod:
    name: str
    params: List[Parameter]  # includes self
    return_type: SawType
    line: int = 0
    column: int = 0
```

**Update Extension node**:
```python
@dataclass
class Extension:
    type_name: str
    type_params: List[TypeParameter]  # For generic extensions
    conformances: List[str]  # Interface names this extension implements
    methods: List[Method]
    init_methods: List[Method]
    line: int = 0
    column: int = 0
```

### 2.4 Type Checker Changes

**Interface registration**:
- Store interface definitions with their required methods
- Track which types implement which interfaces

**Conformance checking**:
- When extension declares `: InterfaceName`, verify all required methods present
- Check method signatures match interface requirements
- Handle `Self` type in return positions

**Interface method lookup**:
- When calling a method, check both direct methods and interface methods

### 2.5 Codegen Changes

**Static dispatch**:
- For now, use static dispatch (no vtables)
- Interface method calls resolve to concrete implementations at compile time
- This works with monomorphization

### 2.6 Implementation Steps

1. [x] Add `INTERFACE` token to lexer
2. [x] Add `Interface` and `InterfaceMethod` AST nodes
3. [x] Parse interface definitions
4. [x] Update `Extension` to support `: InterfaceName` syntax
5. [x] Store interface info in type checker
6. [x] Implement conformance checking
7. [x] Handle `Self` type in interfaces
8. [x] Add tests for interface definition
9. [x] Add tests for interface implementation
10. [x] Add tests for interface method calls

**Status**: Complete (commit pending). Interface definitions, conformance checking, and error detection working.

---

## Phase 3: Interface Bounds

### 3.1 Syntax Design

```saw
// Constrained type parameters
func print_all<T: Display>(items: Vec<T>) {
    // T must implement Display
}

// Multiple bounds
func compare<T: Eq + Ord>(a: T, b: T) -> Bool {
    // T must implement both Eq and Ord
}

// Where clauses (optional, more readable for complex bounds)
func complex<T, U>(a: T, b: U) -> Bool
where T: Display + Clone,
      U: Debug
{
    // ...
}
```

### 3.2 Parser Changes

**Update TypeParameter**:
```python
@dataclass
class TypeParameter:
    name: str
    bounds: List[str]  # Interface names
    line: int = 0
    column: int = 0
```

**Parse bounds**:
```
parse_type_param() -> TypeParameter:
    name = expect(IDENT)
    bounds = []
    if match(':'):
        bounds.append(expect(IDENT))  # First interface
        while match('+'):
            bounds.append(expect(IDENT))
    return TypeParameter(name, bounds)
```

### 3.3 Type Checker Changes

**Bound verification**:
- When instantiating a generic with bounds, verify the concrete type satisfies all bounds
- `print_all<Int>` → verify Int: Display

**Method availability**:
- Within a generic function, only allow calling methods from bounded interfaces
- `T: Display` means `x.display()` is valid

### 3.4 Implementation Steps

1. [x] Update parser to handle `: Interface` bounds
2. [x] Update parser to handle `+` for multiple bounds
3. [x] Verify bounds during type instantiation
4. [x] Allow interface method calls on bounded type parameters
5. [x] Add error messages for unsatisfied bounds
6. [x] Add tests for interface bounds

**Status**: Complete. Interface bounds on generic type parameters working with bound verification.

---

## Phase 4: Associated Types

### 4.1 Syntax Design

```saw
interface Iterator {
    type Item

    func next(var self) -> Item?
}

extension Vec<T>: Iterator {
    type Item = T

    func next(var self) -> T? {
        // ...
    }
}

// Using associated types in bounds
func sum<I: Iterator>(iter: I) -> Int
where I.Item: Add
{
    // ...
}
```

### 4.2 Parser Changes

**Add AssociatedType to Interface**:
```python
@dataclass
class AssociatedType:
    name: str
    bounds: List[str] = field(default_factory=list)
    line: int = 0
    column: int = 0

@dataclass
class Interface:
    # ... existing fields ...
    associated_types: List[AssociatedType]
```

**Add type assignment in extensions**:
```python
@dataclass
class TypeAssignment:
    name: str  # Associated type name
    concrete_type: SawType
    line: int = 0
    column: int = 0
```

### 4.3 Type Checker Changes

- Track associated type assignments in interface implementations
- Resolve `I.Item` to concrete type when I is known
- Verify associated types are defined in implementations

### 4.4 Implementation Steps

1. [ ] Add `AssociatedType` AST node
2. [ ] Parse `type Name` in interfaces
3. [ ] Add `TypeAssignment` AST node
4. [ ] Parse `type Name = ConcreteType` in extensions
5. [ ] Resolve associated types in type checker
6. [ ] Add tests for associated types

---

## Phase 5: Iterator Interface

### 5.1 Define Core Interfaces

```saw
// The core iterator interface
interface Iterator {
    type Item

    func next(var self) -> Item?
}

// Types that can produce an iterator
interface IntoIterator {
    type Item
    type IntoIter: Iterator  // where IntoIter.Item == Item

    func into_iter(self) -> IntoIter
}
```

### 5.2 Implementation for Built-in Types

We'll need arrays/vectors first. Assuming we have `Vec<T>`:

```saw
struct VecIterator<T> {
    vec: Vec<T>
    index: Int
}

extension VecIterator<T>: Iterator {
    type Item = T

    func next(var self) -> T? {
        if self.index < self.vec.len() {
            let item = self.vec[self.index]
            self.index = self.index + 1
            break item  // Using our while-expr pattern!
        }
        None
    }
}

extension Vec<T>: IntoIterator {
    type Item = T
    type IntoIter = VecIterator<T>

    func into_iter(self) -> VecIterator<T> {
        VecIterator(vec: self, index: 0)
    }
}
```

### 5.3 Implementation Steps

1. [ ] Define Iterator interface in standard library
2. [ ] Define IntoIterator interface
3. [ ] Implement for Vec<T> (once we have vectors)
4. [ ] Add tests

---

## Phase 6: Range Types

### 6.1 Syntax Design

```saw
0..10      // Range<Int> - exclusive end
0..=10     // RangeInclusive<Int> - inclusive end
```

### 6.2 Implementation

```saw
struct Range<T> {
    start: T
    end: T
}

struct RangeInclusive<T> {
    start: T
    end: T
}

// Implement Iterator for ranges
extension Range<Int>: Iterator {
    type Item = Int

    func next(var self) -> Int? {
        if self.start < self.end {
            let current = self.start
            self.start = self.start + 1
            break current
        }
        None
    }
}
```

### 6.3 Lexer Changes

Add tokens:
- `DOTDOT` for `..`
- `DOTDOTEQ` for `..=`

### 6.4 Parser Changes

Parse range expressions as binary operators or primary expressions.

### 6.5 Implementation Steps

1. [ ] Add `DOTDOT` and `DOTDOTEQ` tokens
2. [ ] Add `Range` and `RangeInclusive` built-in types
3. [ ] Parse range expressions
4. [ ] Implement Iterator for Range<Int>
5. [ ] Implement Iterator for RangeInclusive<Int>
6. [ ] Add tests for ranges

---

## Phase 7: For Loop

### 7.1 Syntax Design

```saw
for item in collection {
    print(item)
}

for (index, item) in collection.enumerate() {
    print(index)
    print(item)
}

for i in 0..10 {
    print(i)
}
```

### 7.2 Desugaring

For loops desugar to while loops with iterators:

```saw
// for item in collection { body }
// becomes:
{
    var __iter = collection.into_iter()
    while let item = __iter.next() {
        body
    }
}
```

### 7.3 Lexer Changes

Add keyword:
- `FOR` for `for`
- `IN` for `in`

### 7.4 Parser Changes

**New AST node**:
```python
@dataclass
class ForLoop(Statement):
    variable: str  # or pattern for destructuring
    iterable: Expression
    body: Block
    line: int = 0
    column: int = 0
```

### 7.5 Type Checker Changes

- Verify iterable implements IntoIterator
- Infer variable type from Iterator::Item
- Check body with variable in scope

### 7.6 Codegen Changes

Two options:
1. **Desugar in parser/AST** - Transform ForLoop to WhileExpr before codegen
2. **Handle in codegen** - Generate iterator code directly

Option 1 is simpler and reuses existing while loop code.

### 7.7 Implementation Steps

1. [ ] Add `FOR` and `IN` tokens
2. [ ] Add `ForLoop` AST node
3. [ ] Parse for loops
4. [ ] Desugar to while + iterator in type checker or early codegen pass
5. [ ] Add tests for for loops with ranges
6. [ ] Add tests for for loops with collections

---

## Testing Strategy

### Unit Tests
- Generic function instantiation
- Generic struct creation
- Interface definition and implementation
- Interface bound checking
- Associated type resolution
- Iterator implementation
- Range creation and iteration
- For loop with various iterables

### Error Tests
- Missing interface implementation
- Unsatisfied interface bounds
- Incorrect method signature in interface implementation
- Missing associated type
- For loop on non-iterable type

### Integration Tests
- Complete iteration over range
- Complete iteration over collection
- Nested for loops
- For loop with break/continue

---

## Estimated Effort

| Phase | Estimated Time | Dependencies |
|-------|---------------|--------------|
| Phase 1: Basic Generics | 4-6 hours | None |
| Phase 2: Interfaces | 3-4 hours | Phase 1 |
| Phase 3: Interface Bounds | 2-3 hours | Phase 2 |
| Phase 4: Associated Types | 2-3 hours | Phase 3 |
| Phase 5: Iterator Interface | 1-2 hours | Phase 4 + Collections |
| Phase 6: Range Types | 2-3 hours | Phase 5 |
| Phase 7: For Loop | 2-3 hours | Phase 6 |

**Total: ~16-24 hours across multiple sessions**

---

## Open Questions

1. **Syntax for interface bounds**: Use `:` like Rust, or something else?
2. **Where clauses**: Support them, or keep bounds inline only?
3. **Self type**: How to handle `Self` in interface method returns?
4. **Generic inference**: How much type inference for generics?
5. **Orphan rules**: Allow implementing external interfaces for external types?
6. **Collections first?**: Should we implement Vec<T> before or in parallel with generics?

---

## Progress

- **2024-12-25**: Phase 1 generic functions complete (commit 185b27d)
  - Added TypeParameter AST node and TYPE_PARAM type kind
  - Parser handles `<T, U>` with backtracking to disambiguate from `<` comparison
  - Type checker performs type substitution for generic calls
  - Codegen implements monomorphization (e.g., `identity<Int>` → `identity$Int`)
  - 2 test files: `generics_simple.saw`, `generics_multi_param.saw`

- **2024-12-25**: Phase 2 interfaces complete (commit pending)
  - Added INTERFACE token and Interface/InterfaceMethod AST nodes
  - Parser handles `interface Name { ... }` and `extension Type: Interface { ... }`
  - Type checker registers interfaces and checks conformance
  - Detects missing methods and signature mismatches
  - 2 test files: `interface_simple.saw`, `interface_missing_method.saw`

- **2024-12-26**: Phase 3 interface bounds complete
  - Parser handles `<T: Interface>` and `<T: A + B>` bounds
  - Type checker verifies bounds at generic instantiation
  - Proper error messages for unsatisfied bounds
  - 2 test files: `interface_param.saw`, `interface_bound_error.saw`

## Next Steps

1. ~~Start with Phase 1: Basic Generics~~ ✓ (functions done)
2. ~~Begin with generic functions (simpler than generic types)~~ ✓
3. ~~Phase 2: Interfaces~~ ✓
4. ~~Phase 3: Interface bounds (T: Interface)~~ ✓
5. Phase 4: Associated types (type Item) - needed for Iterator
6. Phase 5-7: Iterator, Range, For Loop
