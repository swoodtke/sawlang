#!/usr/bin/env python3
"""Call heads and import bindings: sawc2 resolve against the frozen compiler.

    python compiler/tests/resolve/frozen_check.py [ENTRY.saw]

A one-time check, kept runnable (SL:open-questions D12). The frozen compiler
builds ENTRY, by default the sawc2 driver, in a child process observed the way
`compiler/tools/std_cone.py` observes it; nothing in `sawc/` is edited. Where
the typechecker hands the whole program to the code generator, every body is
typechecked and annotated: the observer reads what the typechecker decided of
each call head (`resolved_symbol`, `module_free_call`, `is_field_call`, the
construction nodes it built) and of each selective import, and stops before
any code is generated. `sawc2 resolve --dump` resolves the same
program, and the two are compared per line of each file of the compiler:

- each call's class: the frozen compiler's struct construction is `init`, its
  enum construction `case`, a function call `overload` (or `init` when the name
  is a type, `local` when it is a closure), a module-qualified call
  `overload`, a call on a type `static-method`, a closure-typed field `value`,
  and any other method call `method`;
- each selective import's name: the kind of declaration it names.

The frozen compiler's answers are checked once and recorded; they are never the
definition. The check prints its agreement counts and every difference.
"""
import collections
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))

import build  # noqa: E402

OBSERVE_FLAG = "--observe"
BUILTIN_FUNCTIONS = ("print", "panic", "assert", "sizeof", "alignof", "sleep", "cancelled")
PRIMITIVES = ("Int", "UInt", "Int8", "Int16", "Int32", "Int64", "UInt8", "UInt16", "UInt32",
              "UInt64", "Float", "Bool", "String", "Optional", "Result", "UnsafePointer",
              "UnsafeConstPointer")
_CALL = re.compile(r"^    \((\d+):(\d+) ([a-z-]+)")
_IMPORT = re.compile(r"^    \((\d+):\d+ ")
_SELECTED = re.compile(r"\((\w+) \(([a-z-]+) ")


class _Stop(BaseException):
    """Raised once every module is typechecked, before code generation."""


def observe(out_path, sawc_argv):
    """Run the frozen compiler in this process and record its call heads and
    import bindings for the modules under compiler/."""
    sys.path.insert(0, os.path.join(REPO, "sawc"))
    import ast_nodes as A
    import ast_walk
    import codegen.core as CC

    calls = []
    imports = []
    compiler_dir = os.path.join(REPO, "compiler") + os.sep

    def in_compiler(path):
        return bool(path) and os.path.abspath(path).startswith(compiler_dir)

    def type_names(program):
        names = set(PRIMITIVES)
        for table in ("structs", "enums", "type_definitions"):
            for d in getattr(program, table):
                names.add(d.name)
        return names

    def classify(node, types):
        if isinstance(node, A.StructInit):
            # The frozen parser guesses `name(label: ...)` is a construction,
            # and its typechecker turns the guess into a call where it was one.
            if node.as_function_call is not None:
                return classify(node.as_function_call, types)
            return "init"
        if isinstance(node, A.MethodCall) and "[]" in node.method_name:
            # A subscript, which the frozen compiler rewrites into a call of
            # its accessor; it is no call in the source.
            return None
        if isinstance(node, A.EnumInit):
            return "case"
        if isinstance(node, A.FunctionCall):
            if node.name in types or node.alias_construction:
                return "init"
            if node.resolved_symbol or node.name in BUILTIN_FUNCTIONS:
                return "overload"
            return "local"
        if isinstance(node, A.MethodCall):
            if node.module_free_call:
                return "overload"
            if node.is_field_call:
                return "value"
            obj = node.object
            if isinstance(obj, A.Identifier) and obj.name in types:
                return "static-method"
            return "method"
        return None

    def top_items(program):
        """Each top-level item that holds code, with its file: the frozen
        compiler checks the program's modules merged into one."""
        for fn in program.functions:
            yield fn, fn.source_file
        for st in program.statics:
            yield st, st.source_file
        for ext in program.extensions:
            for m in ext.methods:
                yield m, ext.source_file
        for tr in program.traits:
            for m in tr.methods:
                yield m, tr.source_file

    def record_program(program):
        types = type_names(program)
        for item, path in top_items(program):
            if not in_compiler(path) or getattr(item, "is_mono_instance", False):
                continue
            rel = os.path.relpath(os.path.abspath(path), REPO)
            stack = [item]
            seen = set()
            while stack:
                node = stack.pop()
                if id(node) in seen:
                    continue
                seen.add(id(node))
                kind = classify(node, types)
                if kind is not None:
                    calls.append([rel, node.line, node.column, kind])
                stack.extend(ast_walk.child_nodes(node))
        record_imports(program)

    def record_imports(program):
        """Each selective import of each compiler file, as the frozen parser
        reads it, and the kind of the declaration of that name in the file its
        path names, as the program the frozen compiler built declares it."""
        kinds = {}
        for table, kind in (("structs", "type"), ("enums", "type"), ("type_definitions", "type"),
                            ("traits", "trait"), ("functions", "function"),
                            ("statics", "static")):
            for d in getattr(program, table):
                if d.source_file:
                    kinds[(os.path.abspath(d.source_file), d.name)] = kind
        for block in program.extern_blocks:
            for f in block.functions:
                if f.source_file:
                    kinds[(os.path.abspath(f.source_file), f.name)] = "function"
        files = sorted({os.path.abspath(p) for _, p in top_items(program) if in_compiler(p)})
        for path in files:
            with open(path, encoding="utf-8") as fh:
                ast = frozen_parse(fh.read(), path)
            rel = os.path.relpath(path, REPO)
            for decl in ast.imports or []:
                target = import_file(decl.path, path)
                for name in decl.symbols or []:
                    imports.append([rel, decl.line, name, kinds.get((target, name), "unknown")])

    def import_file(parts, importer):
        if parts[0] == "std":
            return os.path.join(REPO, "sawc", "std", *parts[1:]) + ".saw"
        for name, directory in build.STAGE_PACKAGES:
            if parts[0] == name:
                return os.path.join(REPO, directory, *parts[1:]) + ".saw"
        return os.path.join(os.path.dirname(importer), *parts) + ".saw"

    # Code generation receives the whole program, its modules merged and every
    # body typechecked; that is where the answers are read, before any code.
    def generate(self, program):
        record_program(program)
        raise _Stop()
    CC.CodeGenerator.generate = generate

    import sawc as frozen
    frozen_parse = frozen.parse_source
    sys.argv = ["sawc.py"] + list(sawc_argv)
    status = "no stop"
    try:
        frozen.main()
    except _Stop:
        status = "ok"
    except SystemExit as e:
        status = "exit %s" % (e.code,)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"status": status, "calls": calls, "imports": imports}, fh)
    return 0


def frozen_answers(entry):
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    argv = build.sawc_arguments(entry, os.path.join(REPO, ".build", "frozen-check"))
    subprocess.run([sys.executable, os.path.abspath(__file__), OBSERVE_FLAG, out, "--"] + argv,
                   cwd=REPO, check=False)
    with open(out, encoding="utf-8") as fh:
        data = json.load(fh)
    os.remove(out)
    return data


def module_file(identity, entry_rel):
    """The file a module identity of the compiler's build names."""
    for name, directory in build.STAGE_PACKAGES:
        if identity.startswith(name + "."):
            return os.path.join(directory, *identity.split(".")[1:]) + ".saw"
    return entry_rel


def sawc2_answers(entry_rel):
    args = [build.SAWC2, "resolve", "--dump"]
    for name, directory in build.STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, directory)]
    r = subprocess.run(args + [entry_rel], cwd=REPO, capture_output=True, text=True)
    calls = []
    imports = []
    current = None
    section = None
    for line in r.stdout.split("\n"):
        if line.startswith("(Module "):
            current = module_file(line[len("(Module "):].strip(), entry_rel)
            section = None
        elif line.startswith("  ("):
            section = line.strip()[1:].split(" ")[0].rstrip(")")
        m = _CALL.match(line)
        if section == "calls" and m:
            calls.append([current, int(m.group(1)), int(m.group(2)), m.group(3)])
        if section == "imports" and _IMPORT.match(line) and "(select" in line:
            row = int(_IMPORT.match(line).group(1))
            for name, kind in _SELECTED.findall(line.split("(select", 1)[1]):
                imports.append([current, row, name, kind])
    return calls, imports


# The kind of declaration a selective import names, as each side spells it.
IMPORT_KINDS = {"struct": "type", "enum": "type", "alias": "type", "trait": "trait",
                "overload": "function", "static": "static", "module": "module"}


def main(argv):
    if len(argv) >= 3 and argv[0] == OBSERVE_FLAG and argv[2] == "--":
        return observe(argv[1], argv[3:])
    entry = os.path.abspath(argv[0]) if argv else build.DRIVER_ENTRY
    entry_rel = os.path.relpath(entry, REPO)
    frozen = frozen_answers(entry)
    if frozen["status"] != "ok":
        print("frozen check: the frozen compiler stopped with %s" % frozen["status"])
        return 1
    calls, imports = sawc2_answers(entry_rel)

    def per_line(rows):
        out = collections.defaultdict(collections.Counter)
        for f, line, _col, kind in rows:
            out[(f, line)][kind] += 1
        return out
    theirs = per_line(frozen["calls"])
    ours = per_line(calls)
    agree = 0
    differences = []
    for key in sorted(set(theirs) | set(ours)):
        a, b = theirs.get(key, collections.Counter()), ours.get(key, collections.Counter())
        if a == b:
            agree += sum(a.values())
        else:
            differences.append("%s:%d: frozen %s, sawc2 %s"
                               % (key[0], key[1], dict(sorted(a.items())), dict(sorted(b.items()))))
    frozen_imports = {}
    names = {}
    for f, line, name, kind in frozen["imports"]:
        frozen_imports[(f, line, name)] = kind
    for f, line, name, kind in imports:
        names[(f, line, name)] = IMPORT_KINDS.get(kind, kind)
    import_diffs = []
    for key in sorted(set(frozen_imports) | set(names)):
        if key not in frozen_imports or key not in names:
            import_diffs.append("%s:%d: %s bound by only %s" % (
                key[0], key[1], key[2], "the frozen compiler" if key in frozen_imports else "sawc2"))
        elif names[key] != frozen_imports[key]:
            import_diffs.append("%s:%d: %s is a %s to the frozen compiler, a %s to sawc2"
                                % (key[0], key[1], key[2], frozen_imports[key], names[key]))
    for line in differences + import_diffs:
        print("DIFFERENCE: " + line)
    print("frozen check: %d call heads agree, %d lines differ; %d import bindings, %d differ"
          % (agree, len(differences), len(names), len(import_diffs)))
    return 1 if differences or import_diffs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
