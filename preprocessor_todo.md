# Type Resolution Preprocessing - Design Notes

## Problem Statement

The typechecker has two parallel systems for looking up types:

1. **Namespace system** (`self.namespace`) - Handles module-qualified lookups like `toml.TomlDoc`, properly resolves visibility and imports
2. **Legacy registries** (`self.structs`, `self.enums`, `self.functions`, `self.traits`) - Store actual type information (fields, methods, variants, etc.)

When code uses module-qualified types like `toml.TomlDoc.parse()`:
- The namespace correctly resolves `toml.TomlDoc` to a STRUCT symbol
- But then `self.structs.get("TomlDoc")` fails because `TomlDoc` is defined in the `toml` module, not the current module's registry

This causes confusing errors like "method takes 0 arguments" when the method actually exists but the struct info wasn't found.

### Symptoms

- Static method calls on module-qualified types fail
- Struct fields using imported types may not resolve correctly
- Function parameters/returns using imported types may fail
- Generic type arguments referencing imported types may fail

## Current Workarounds

We've been adding special cases throughout the typechecker to handle module-qualified access, e.g.:
- `_check_method_call` has special handling for `MemberAccess` objects
- `_check_member_access` has special handling for module lookups

This is fragile and leads to inconsistent behavior.

## Proposed Solutions

### Option 1: Merge Module Type Info (Quick Fix)

After type-checking each module, merge its type info into the main typechecker's registries:

```python
# After checking each module
typechecker.structs.update(module_typechecker.structs)
typechecker.enums.update(module_typechecker.enums)
# etc.
```

**Pros:** Simple, minimal code changes
**Cons:** Name collisions between modules, doesn't fix the architectural issue

### Option 2: Type Resolution Pass (Medium-term)

Add a preprocessing pass that walks the AST before type-checking:

1. **Collect all visible types** - Walk imports/modules and build a complete type registry
2. **Resolve type references** - Walk all `SawType` nodes in the AST and resolve them to canonical form
3. **Store resolutions** - Attach resolution info to AST nodes for later use
4. **Validate existence** - Report "unknown type" errors early

```python
class TypeResolver:
    def resolve_program(self, program: Program, namespace: Namespace):
        # Resolve all type references in:
        # - Struct field types
        # - Function parameter/return types
        # - Variable type annotations
        # - Generic type arguments
        # - Extension target types
        pass
```

**Pros:** Clean separation of concerns, better error messages
**Cons:** More code, another pass over the AST

### Option 3: Consolidate Into Namespaces (Long-term Goal)

Migrate all type information into the namespace system, eliminating the legacy registries:

1. **Namespace stores full type info** - `StructSymbol` contains fields, methods, etc. (not just metadata)
2. **Single lookup path** - All type lookups go through namespace resolution
3. **Remove legacy registries** - Delete `self.structs`, `self.enums`, etc.

```python
# Instead of:
struct_info = self.structs.get(name)

# Use:
symbol = self.namespace.resolve(name)
if symbol.kind == SymbolKind.STRUCT:
    # symbol contains all struct info directly
```

**Pros:** Single source of truth, cleaner architecture, proper module scoping
**Cons:** Significant refactor, need to update all lookup sites

## Recommended Approach

1. **Immediate:** Apply Option 1 (merge) to unblock Blade compilation
2. **Next:** Implement Option 2 (resolution pass) for robustness
3. **Eventually:** Work toward Option 3 (namespace consolidation) as part of module system completion

## Files to Modify

- `sawc/sawc.py` - Module compilation, type info merging
- `sawc/typechecker/core.py` - Add resolution pass, update registries
- `sawc/typechecker/expressions.py` - Update type lookups
- `sawc/typechecker/statements.py` - Update type lookups
- `sawc/typechecker/registration.py` - Update type registration
- `sawc/namespace.py` - Expand symbol info storage

## Related Issues

- Error reporting for multi-file compilation (fixed separately)
- Method resolution for module-qualified types
- Generic type parameter substitution across modules
