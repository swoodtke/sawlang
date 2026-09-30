#!/usr/bin/env python3
"""Resolve's three tables against the frozen compiler's view of today's std.

    python compiler/tests/resolve/prelude_check.py

A one-time check, kept runnable (SL:open-questions D12). It reads resolve's
tables from their source, `compiler/resolve/src/prelude.saw` and
`load_std_modules` in `loader.saw`, loads the frozen compiler's builtins in
this process, and prints every difference:

- the std module table against the files under `sawc/std`;
- the synthetic builtin declarations against what `builtin.saw` and std
  declare, which must be nothing of those names, and against the builtin
  names the frozen compiler knows;
- the prelude table against the names the frozen compiler makes visible with
  no import, each with the file that declares it. The frozen compiler builds its
  prelude by exclusion (`IMPORT_REQUIRED_STD_*`, `_is_prelude` in
  `sawc/sawc.py`), so its set is sorted into what a curated core leaves out.

It exits 0 when the only differences are the ones `EXPECTED_ONLY_FROZEN` and
`EXPECTED_ONLY_RESOLVE` explain, and 1 otherwise.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SRC = os.path.join(REPO, "compiler", "resolve", "src")
STD = os.path.join(REPO, "sawc", "std")

_PRELUDE = re.compile(r'p\.prelude_name\("(\w+)", "([\w.]+)"\)')
_SYNTHETIC = re.compile(r'p\.builtin_(?:type|function)\("(\w+)"\)|p\.builtin_decl\("(\w+)", ResDeclKind\.(\w+)')
_STD_MODULE = re.compile(r'self\.std_module\("([\w.]+)"\)')

# Names only the frozen compiler's prelude holds, by why a curated core leaves
# them out. A name matching none of these is a difference.
EXPECTED_ONLY_FROZEN = (
    ("a runtime or compiler-internal name, `__` first", lambda n, kind, public: n.startswith("__")),
    ("an extern C declaration std makes for itself", lambda n, kind, public: kind == "extern"),
    ("a std file's private function", lambda n, kind, public: kind == "function" and not public),
)
# Names only resolve's prelude holds: the frozen compiler knows them in its
# typechecker, not as declarations it marks visible.
EXPECTED_ONLY_RESOLVE = frozenset({
    "Int", "UInt", "Int8", "Int16", "Int32", "Int64", "UInt8", "UInt16", "UInt32", "UInt64",
    "Float", "Bool", "String", "Void", "Never", "Optional", "UnsafePointer",
    "UnsafeConstPointer", "print", "panic", "assert", "sizeof", "alignof", "sleep", "cancelled",
})


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def resolve_tables():
    prelude = dict(_PRELUDE.findall(read(os.path.join(SRC, "prelude.saw"))))
    synthetic = set()
    for plain, decl, kind in _SYNTHETIC.findall(read(os.path.join(SRC, "prelude.saw"))):
        if plain:
            synthetic.add(plain)
        elif kind != "Case":
            synthetic.add(decl)
    std_modules = set(_STD_MODULE.findall(read(os.path.join(SRC, "loader.saw"))))
    return prelude, synthetic, std_modules


def std_files():
    out = set()
    for path in glob.glob(os.path.join(STD, "**", "*.saw"), recursive=True):
        out.add(os.path.relpath(path, STD)[:-len(".saw")].replace(os.sep, "."))
    return out


def frozen_view():
    """(accessible names -> std leaf or 'builtin', declared names -> kind and
    public flag) from the frozen compiler's own builtin namespace."""
    sys.path.insert(0, os.path.join(REPO, "sawc"))
    import sawc  # noqa: E402
    ast, ns = sawc.build_builtin_namespace()
    leaf_of = ns._std_symbol_file
    from ast_nodes import Visibility  # noqa: E402
    kinds = {}
    for f in ast.functions:
        kinds[f.name] = ("function", getattr(f, "visibility", Visibility.PRIVATE)
                         != Visibility.PRIVATE)
    for block in ast.extern_blocks:
        for f in block.functions:
            kinds[f.name] = ("extern", False)
    for table in ("structs", "enums", "traits", "type_definitions"):
        for d in getattr(ast, table):
            kinds.setdefault(d.name, ("type", True))
    accessible = {}
    for name in ns.directly_accessible:
        leaf = leaf_of.get(name)
        accessible[name] = "std." + leaf if leaf and leaf != "builtin" else (leaf or "builtin")
    return accessible, kinds


def main():
    prelude, synthetic, std_modules = resolve_tables()
    problems = []
    notes = []

    files = std_files()
    for m in sorted(files - std_modules):
        problems.append("std module %s is not in load_std_modules' table" % m)
    for m in sorted(std_modules - files):
        problems.append("load_std_modules lists %s, which has no file" % m)

    accessible, kinds = frozen_view()
    for name in sorted(synthetic):
        if name in kinds:
            problems.append("synthetic builtin %s is declared by builtin.saw or std too" % name)

    for name in sorted(set(accessible) - set(prelude)):
        kind, public = kinds.get(name, ("type", True))
        reason = None
        for why, test in EXPECTED_ONLY_FROZEN:
            if test(name, kind, public):
                reason = why
                break
        if reason is None:
            problems.append("the frozen prelude has %s (%s), the prelude table does not"
                            % (name, accessible[name]))
        else:
            notes.append("frozen only, %s: %s" % (reason, name))
    for name in sorted(set(prelude) - set(accessible)):
        if name in EXPECTED_ONLY_RESOLVE:
            notes.append("resolve only, a name the frozen typechecker knows: %s" % name)
        else:
            problems.append("the prelude table has %s (%s), the frozen prelude does not"
                            % (name, prelude[name]))
    for name in sorted(set(prelude) & set(accessible)):
        if prelude[name] != accessible[name]:
            problems.append("%s: the prelude table says %s, the frozen compiler %s"
                            % (name, prelude[name], accessible[name]))

    for line in notes:
        print(line)
    for line in problems:
        print("DIFFERENCE: " + line)
    print("prelude check: %d prelude names, %d synthetic builtins, %d std modules: %s"
          % (len(prelude), len(synthetic), len(std_modules),
             "%d difference(s)" % len(problems) if problems else "no unexplained difference"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
