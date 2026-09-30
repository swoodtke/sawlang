#!/usr/bin/env python3
"""Field, parameter and result types, and Copy tiers: sawc2 typecheck against
the frozen compiler.

    python compiler/tests/typecheck/frozen_check.py [ENTRY.saw]

A one-time check, kept runnable, as `compiler/tests/resolve/frozen_check.py` is.
The frozen compiler builds ENTRY, by default the sawc2 driver, in a child
process observed the way `compiler/tools/std_cone.py` observes it; nothing in
`sawc/` is edited. Where the typechecker hands the whole program to the code
generator, the observer reads, for every declaration under `compiler/`:

- each struct's field types, and its Copy tier from `copy_tier`;
- each enum's Copy tier;
- each free function's and method's parameter and result types.

`sawc2 typecheck --dump` checks the same program, and the two are compared by
file, line and name. Two spellings are made comparable first: a canonical
type's module qualifiers are dropped, since the frozen compiler renders the
short name, and so is `GlobalAllocator`, `Vector`'s default argument, which
only one side fills; an alias is transparent to sawc2, so the frozen `Byte` is
read as `UInt8`. The `deinit` the frozen compiler synthesizes into a policy
conformance, which sawc2 records in the conformance table as implicit, is left
out. The frozen tiers `free` and `implicit` are both Copy; its
`abstract`, a type that mentions a parameter, is compared with sawc2's rule
over the arguments. The frozen compiler's answers are checked once and
recorded; they are never the definition.
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
TIERS = {"free": "Copy", "implicit": "Copy", "explicit": "ExplicitCopy", "nocopy": "NoCopy",
         "abstract": "abstract"}
_QUALIFIER = re.compile(r"\b(?:[a-z_][a-z0-9_]*\.)+(?=[A-Z])")


class _Stop(BaseException):
    """Raised once every module is typechecked, before code generation."""


def observe(out_path, sawc_argv):
    """Run the frozen compiler in this process and record the signatures and
    tiers of the declarations under compiler/."""
    sys.path.insert(0, os.path.join(REPO, "sawc"))
    import ast_nodes as A
    import codegen.core as CC

    compiler_dir = os.path.join(REPO, "compiler") + os.sep
    fields = []
    tiers = []
    functions = []

    def rel_of(path):
        if not path or not os.path.abspath(path).startswith(compiler_dir):
            return None
        return os.path.relpath(os.path.abspath(path), REPO)

    def param_text(p):
        text = str(p.type)
        if p.is_reference and not text.startswith("&"):
            text = ("&var " if p.reference_mutable else "&") + text
        return text

    def tier_of(namespace, saw_type):
        try:
            return TIERS.get(namespace.copy_tier(saw_type), "?")
        except Exception as e:  # noqa: BLE001 - recorded as the frozen answer
            return "raised %s" % type(e).__name__

    def generate(self, program):
        ns = self.namespace
        for s in program.structs:
            rel = rel_of(getattr(s, "source_file", ""))
            if rel is None or getattr(s, "is_mono_instance", False):
                continue
            for f in s.fields:
                fields.append([rel, s.name, f.name, str(f.type)])
            st = A.SawType(A.TypeKind.STRUCT, struct_name=getattr(s, "type_identity", "") or s.name)
            if s.type_params:
                st.type_args = [A.SawType(A.TypeKind.STRUCT, struct_name=tp.name)
                                for tp in s.type_params]
            tiers.append([rel, s.name, tier_of(ns, st)])
        for e in program.enums:
            rel = rel_of(getattr(e, "source_file", ""))
            if rel is None:
                continue
            et = A.SawType(A.TypeKind.ENUM, enum_name=getattr(e, "type_identity", "") or e.name)
            tiers.append([rel, e.name, tier_of(ns, et)])
        for fn in program.functions:
            rel = rel_of(fn.source_file)
            if rel is None or getattr(fn, "is_mono_instance", False):
                continue
            functions.append([rel, fn.line, fn.name,
                              [param_text(p) for p in fn.parameters if p.name != "self"],
                              str(fn.return_type)])
        for ext in program.extensions:
            rel = rel_of(ext.source_file)
            if rel is None:
                continue
            for m in ext.methods:
                if getattr(m, "is_mono_instance", False) or m.line is None:
                    continue
                if m.name == "deinit" and m.line == ext.line:
                    # The drop the frozen compiler synthesizes into a
                    # policy conformance; sawc2 records it as implicit.
                    continue
                result = str(m.return_type)
                functions.append([rel, m.line, m.name,
                                  [param_text(p) for p in m.parameters if p.name != "self"],
                                  result])
        raise _Stop()
    CC.CodeGenerator.generate = generate

    import sawc as frozen
    sys.argv = ["sawc.py"] + list(sawc_argv)
    status = "no stop"
    try:
        frozen.main()
    except _Stop:
        status = "ok"
    except SystemExit as e:
        status = "exit %s" % (e.code,)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"status": status, "fields": fields, "tiers": tiers,
                   "functions": functions}, fh)
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


def normal(text):
    """A type spelling with module qualifiers and `Vector`'s default dropped,
    and the alias `Byte` spelled as the `UInt8` it stands for."""
    text = _QUALIFIER.sub("", text)
    text = re.sub(r"\bByte\b", "UInt8", text)
    return text.replace(", GlobalAllocator", "")


def balanced(text):
    """`text` without the closing parens past its own, which end enclosing lists."""
    while text.count(")") > text.count("("):
        text = text[:-1]
    return text


def groups(text):
    """The top-level parenthesized groups of `text`, each without its parens."""
    out = []
    depth = 0
    start = None
    for i, c in enumerate(text):
        if c == "(":
            depth += 1
            if depth == 1:
                start = i + 1
        elif c == ")":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(text[start:i])
            if depth < 0:
                break
    return out


def sawc2_answers(entry_rel):
    args = [build.SAWC2, "typecheck", "--dump"]
    for name, directory in build.STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, directory)]
    r = subprocess.run(args + [entry_rel], cwd=REPO, capture_output=True, text=True)
    fields = []
    tiers = []
    functions = []
    current = None
    section = None
    for line in r.stdout.split("\n"):
        if line.startswith("(Module "):
            current = module_file(line[len("(Module "):].strip(), entry_rel)
            section = None
            continue
        if line.startswith("  (") and not line.startswith("    "):
            section = line.strip()[1:].split(" ")[0].rstrip(")")
            continue
        body = balanced(line.strip())
        if section == "declarations":
            m = re.match(r"^\(field (\w+)\.(\w+) \d+:\d+ \w+ (.*)\)$", body)
            if m:
                fields.append([current, m.group(1), m.group(2), normal(m.group(3))])
                continue
            m = re.match(r"^\((func|method|init) ([\w.\[\]=]+) (\d+):\d+ \w+ \(signature (.*)\)\)$",
                         body)
            if m:
                name = m.group(2).split(".")[-1]
                sig = m.group(4)
                params = []
                for g in groups(sig):
                    if g.startswith("params"):
                        for p in groups(g[len("params"):]):
                            words = p.split(" ")
                            params.append(normal(" ".join(words[1:-1]).replace(" default", "")))
                result = sig.rsplit(" -> ", 1)[1]
                for suffix in (" static", " default-body", " variadic", " blocking",
                               " synthesize-shared"):
                    result = result.replace(suffix, "")
                functions.append([current, int(m.group(3)), name, params, normal(result)])
        elif section == "copy-tier":
            m = re.match(r"^\(([\w.]+) (.*)\)$", body)
            if m:
                tier = m.group(2).replace(" declared", "")
                if tier.startswith("(join"):
                    tier = "rule"
                tiers.append([current, m.group(1).split(".")[-1], tier])
    return fields, tiers, functions


def compare(label, theirs, ours, key_of, value_of):
    a = {key_of(row): value_of(row) for row in theirs}
    b = {key_of(row): value_of(row) for row in ours}
    agree = 0
    diffs = []
    for key in sorted(set(a) | set(b), key=str):
        if key not in a or key not in b:
            diffs.append("%s %s: only %s has it" % (label, key,
                                                     "the frozen compiler" if key in a else "sawc2"))
        elif a[key] == b[key]:
            agree += 1
        else:
            diffs.append("%s %s: frozen %s, sawc2 %s" % (label, key, a[key], b[key]))
    return agree, diffs


def main(argv):
    if len(argv) >= 3 and argv[0] == OBSERVE_FLAG and argv[2] == "--":
        return observe(argv[1], argv[3:])
    entry = os.path.abspath(argv[0]) if argv else build.DRIVER_ENTRY
    entry_rel = os.path.relpath(entry, REPO)
    frozen = frozen_answers(entry)
    if frozen["status"] != "ok":
        print("frozen check: the frozen compiler stopped with %s" % frozen["status"])
        return 1
    fields, tiers, functions = sawc2_answers(entry_rel)
    their_fields = [[f, s, n, normal(t)] for f, s, n, t in frozen["fields"]]
    fa, fd = compare("field", their_fields, fields, lambda r: (r[0], r[1], r[2]), lambda r: r[3])
    their_tiers = [[f, n, "rule" if t == "abstract" else t] for f, n, t in frozen["tiers"]]
    ta, td = compare("tier", their_tiers, tiers, lambda r: (r[0], r[1]), lambda r: r[2])
    their_functions = [[f, l, n, [normal(p) for p in ps], normal(r)]
                       for f, l, n, ps, r in frozen["functions"]]
    sa, sd = compare("signature", their_functions, functions, lambda r: (r[0], r[1], r[2]),
                     lambda r: (tuple(r[3]), r[4]))
    for line in fd + td + sd:
        print("DIFFERENCE: " + line)
    print("frozen check: %d field types agree, %d differ; %d signatures agree, %d differ; "
          "%d Copy tiers agree, %d differ" % (fa, len(fd), sa, len(sd), ta, len(td)))
    return 1 if fd or td or sd else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
