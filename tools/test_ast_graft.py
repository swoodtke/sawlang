#!/usr/bin/env python3
"""Design 126's "zero grafted AST writes" exit criterion, mechanized (design 194
unit 1).

126 declared 79 of the 89 attributes the passes stamp on AST nodes as typed
annotation fields, and its exit criterion said the remaining grafts were gone.
It was checked once, by hand, and then nothing policed it — so grafts crept back,
eleven of them by the design-190 census. A graft is not a style problem:

  * `substitute_ast_types` (the monomorphizer) walks `dataclasses.fields()`, so a
    grafted `SawType` is INVISIBLE to it and survives monomorphization
    un-substituted. That is the RC-2 bug 126 fixed, and every new graft re-opens
    it for its own field.
  * `structural_fields()` is how child walkers tell structure from metadata. An
    undeclared field is in neither list, so no walker can be right about it.
  * a reader has no way to know the field exists, its type, or its default —
    which is why grafted fields are read through `getattr(node, 'x', None)` and
    why Pyright cannot see any of it.

So: EVERY attribute created by assignment in `sawc/` must be DECLARED on a class
in `sawc/`. "Declared" means one of

  * a class-level annotation or assignment (a dataclass field, a class constant),
  * a name in `__slots__`,
  * a `self.<name> = ...` somewhere in the owning class's own methods

— i.e. the three ways Python spells "this object has this attribute". An
assignment through anything else creates a field out of thin air, and that is
what this rejects.

Two escape hatches, both narrow and both requiring a diff to widen:

  * FOREIGN_ATTRS — attributes of objects sawc does not define (llvmlite's
    `linkage`, `section`, `volatile`, ...). Keyed by name AND by the file prefix
    allowed to write it, so `linkage` is writable in codegen and nowhere else.
  * DYNAMIC_SETATTR — `setattr(obj, <expr>, v)` sites whose name is computed. The
    reflective field walkers (`for f in dataclasses.fields(node): setattr(node,
    f.name, ...)`) are recognized automatically, since a name that came out of
    `fields()` is declared by construction; anything else is listed here with a
    reason.

Run from the repo root:  ./.venv/bin/python tools/test_ast_graft.py
Exit code 0 = pass; nonzero (with a diagnostic naming each graft) = fail.
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO, "sawc")

# Attributes of objects sawc does not define: `name -> (owner, file prefixes)`.
# The prefix list is the point — it keeps a foreign name from covering a graft
# somewhere else in the compiler.
FOREIGN_ATTRS = {
    "linkage": ("llvmlite ir.GlobalValue", ("sawc/codegen/",)),
    "section": ("llvmlite ir.GlobalValue", ("sawc/codegen/",)),
    "align": ("llvmlite ir.GlobalVariable / AllocaInstr", ("sawc/codegen/",)),
    "global_constant": ("llvmlite ir.GlobalVariable", ("sawc/codegen/",)),
    "volatile": ("llvmlite ir.LoadInstr / StoreInstr", ("sawc/codegen/",)),
    "data_layout": ("llvmlite ir.Module", ("sawc/codegen/",)),
    "debug_metadata": ("llvmlite ir.IRBuilder", ("sawc/codegen/",)),
    # The two below patch llvmlite's instruction CLASSES at import time so a
    # `load`/`store` can carry `volatile` (see codegen/core.py's note).
    "descr": ("llvmlite ir.LoadInstr / StoreInstr (class patch)",
              ("sawc/codegen/core.py",)),
    "_saw_volatile_patched": ("llvmlite ir.LoadInstr (class patch guard)",
                              ("sawc/codegen/core.py",)),
}

# `setattr` sites whose attribute NAME is an expression, keyed by
# `file:line-independent` site signature -> reason. The signature is the
# unparsed name expression, so moving the code does not need an edit here but
# introducing a new dynamic graft does.
DYNAMIC_SETATTR = {
    # `for _slot in ("bounds", "parent_traits", "conformances")` — three
    # declared fields, canonicalized in place.
    "_slot": "typechecker/types.py: a literal tuple of three declared fields",
    # `_restore_authored_callee(node, attr)` with attr in {"name",
    # "method_name"} — both declared on FunctionCall / MethodCall.
    "attr": "typechecker/expressions.py: 'name' | 'method_name', both declared",
    # `_VC_HEAD_FIELD[type(cond)]` — a table of declared child-field names.
    "field": "coro_transform.py: a table of declared head-position fields",
    # `_derivation_slot`'s flag, one of the `is_derived_*` Method fields.
    "flag": "typechecker/registration.py: an `is_derived_*` Method field",
    # `Expression.__deepcopy__` copies `self.__dict__`, whose keys are by
    # construction the fields the source object already has.
    "k": "ast_nodes.py: __deepcopy__ over the source object's own __dict__",
}

# The names `setattr(node, X, ...)` may take when X came out of a fields() walk.
_FIELDS_ITER = {"fields", "structural_fields"}


def py_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def declared_in(tree):
    """Every attribute name any class in this module declares, by any of the
    three spellings. Returns `name -> {class name}`."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                out.setdefault(stmt.target.id, set()).add(node.name)
            elif isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if not isinstance(t, ast.Name):
                        continue
                    out.setdefault(t.id, set()).add(node.name)
                    if t.id == "__slots__":
                        for elt in getattr(stmt.value, "elts", []):
                            if isinstance(elt, ast.Constant):
                                out.setdefault(elt.value, set()).add(node.name)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(stmt):
                    targets = []
                    if isinstance(sub, ast.Assign):
                        targets = sub.targets
                    elif isinstance(sub, (ast.AugAssign, ast.AnnAssign)):
                        targets = [sub.target]
                    for t in targets:
                        if (isinstance(t, ast.Attribute)
                                and isinstance(t.value, ast.Name)
                                and t.value.id == "self"):
                            out.setdefault(t.attr, set()).add(node.name)
    return out


def fields_loop_vars(tree):
    """Loop variables bound by `for <v> in ...fields(...)`, whose `.name` is a
    declared field by construction."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.comprehension)):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        # `dataclasses.fields(x)` / `structural_fields(x)`, possibly wrapped.
        for sub in ast.walk(node.iter):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            fname = (fn.attr if isinstance(fn, ast.Attribute)
                     else getattr(fn, "id", None))
            if fname in _FIELDS_ITER:
                names.add(node.target.id)
                break
    return names


def foreign_ok(name, rel):
    entry = FOREIGN_ATTRS.get(name)
    if entry is None:
        return False
    return any(rel.startswith(p) for p in entry[1])


def main():
    files = py_files(SAWC)
    schema = {}
    for path in files:
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        rel = os.path.relpath(path, REPO)
        for name, classes in declared_in(tree).items():
            schema.setdefault(name, set()).update(f"{rel}:{c}" for c in classes)

    grafts = []
    for path in files:
        rel = os.path.relpath(path, REPO)
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        field_vars = fields_loop_vars(tree)
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for t in targets:
                if not isinstance(t, ast.Attribute):
                    continue
                if isinstance(t.value, ast.Name) and t.value.id == "self":
                    continue
                if t.attr in schema or foreign_ok(t.attr, rel):
                    continue
                grafts.append((rel, node.lineno, ast.unparse(t),
                               "no class in sawc/ declares this attribute"))
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "setattr" and len(node.args) >= 2):
                continue
            arg = node.args[1]
            if isinstance(arg, ast.Constant):
                if isinstance(arg.value, str) and not (
                        arg.value in schema or foreign_ok(arg.value, rel)):
                    grafts.append((rel, node.lineno, ast.unparse(node)[:72],
                                   "setattr of an undeclared attribute"))
                continue
            # A computed name: allowed when it came out of a fields() walk,
            # otherwise it has to be listed with a reason.
            if (isinstance(arg, ast.Attribute) and arg.attr == "name"
                    and isinstance(arg.value, ast.Name)
                    and arg.value.id in field_vars):
                continue
            key = ast.unparse(arg)
            if key in DYNAMIC_SETATTR:
                continue
            grafts.append((rel, node.lineno, ast.unparse(node)[:72],
                           f"computed setattr name `{key}` is not accounted for"))

    if grafts:
        print("AST GRAFT GATE FAILED — design 126's exit criterion is broken.")
        print()
        print("Each site below creates an attribute no class declares. Declare it")
        print("(an `annotation(...)` field on the node class, a `self.x = ...` in")
        print("the owning class's __init__), or — if the object is not sawc's —")
        print("add it to FOREIGN_ATTRS in this file with the file prefix that may")
        print("write it.")
        print()
        for rel, lineno, text, why in grafts:
            print(f"  {rel}:{lineno}")
            print(f"      {text}")
            print(f"      {why}")
        print()
        print(f"{len(grafts)} grafted write(s).")
        return 1

    print(f"ast-graft gate: {len(schema)} declared attribute names across "
          f"{len(files)} files in sawc/; zero grafted writes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
