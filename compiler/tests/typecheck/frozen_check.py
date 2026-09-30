#!/usr/bin/env python3
"""Field, parameter and result types, Copy tiers, call targets and binding
types: sawc2 typecheck against the frozen compiler.

    python compiler/tests/typecheck/frozen_check.py [ENTRY.saw]

A one-time check, kept runnable, as `compiler/tests/resolve/frozen_check.py` is.
The frozen compiler builds ENTRY, by default the sawc2 driver, in a child
process observed the way `compiler/tools/std_cone.py` observes it; nothing in
`sawc/` is edited. Where the typechecker hands the whole program to the code
generator, the observer reads, for every declaration under `compiler/`:

- each struct's field types, and its Copy tier from `copy_tier`;
- each enum's Copy tier;
- each free function's and method's parameter and result types;
- in each body, every call's callee, the overload or module its resolution
  picked, its receiver's type and its type arguments, and every `let` and
  `var` binding's type.

Calls are compared by file, line and callee name, as a multiset per key, since
the frozen compiler places a method call at its `.` and sawc2 at its receiver.
A subscript and the frozen compiler's lowered subscript writes are left out:
their type arguments are the frozen window's result, not an instantiation.

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

    import dataclasses

    compiler_dir = os.path.join(REPO, "compiler") + os.sep
    fields = []
    tiers = []
    functions = []
    calls = []
    lets = []

    def walk_body(node, rel, seen):
        """Every call and `let` under `node`, which the typechecker annotated."""
        if id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, list):
            for x in node:
                walk_body(x, rel, seen)
            return
        if not dataclasses.is_dataclass(node) or isinstance(node, type):
            return
        if isinstance(node, A.FunctionCall):
            calls.append([rel, node.line, node.name, node.resolved_symbol or "", "",
                          [str(t) for t in (node.type_args or [])]])
        elif isinstance(node, A.MethodCall):
            receiver = getattr(node.object, "resolved_type", None)
            calls.append([rel, node.line, node.method_name, node.resolved_symbol or "",
                          str(receiver) if receiver is not None else "",
                          [str(t) for t in (node.type_args or [])]])
        elif isinstance(node, A.LetStatement):
            t = node.type_annotation
            if t is None:
                t = getattr(node.value, "resolved_type", None)
            lets.append([rel, node.line, node.name, str(t)])
        for f in dataclasses.fields(node):
            if f.name not in ("resolved_type", "expected_type"):
                walk_body(getattr(node, f.name), rel, seen)

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
        seen = set()
        for fn in program.functions:
            rel = rel_of(fn.source_file)
            if rel is None or getattr(fn, "is_mono_instance", False):
                continue
            functions.append([rel, fn.line, fn.name,
                              [param_text(p) for p in fn.parameters if p.name != "self"],
                              str(fn.return_type)])
            walk_body(fn.body, rel, seen)
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
                walk_body(m.body, rel, seen)
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
                   "functions": functions, "calls": calls, "lets": lets}, fh)
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


_BODY_LINE = re.compile(r"^\((\d+):(\d+)-\d+:\d+ (\S+) (.*?) (place|value) "
                        r"(move|copy|temp|borrow|borrow-var|project|write|update|test|unused)"
                        r"( \(.*\))?\)$")


def body_row(line):
    """(line, column, kind, type, call text) of a `bodies` line, or None; the
    type drops the adjustments that follow it."""
    m = _BODY_LINE.match(line)
    if not m:
        return None
    text = m.group(4)
    while text.endswith(")"):
        depth = 0
        opener = -1
        for i in range(len(text) - 1, -1, -1):
            if text[i] == ")":
                depth += 1
            elif text[i] == "(":
                depth -= 1
                if depth == 0:
                    opener = i
                    break
        if opener <= 0 or text[opener - 1] != " " or \
                text[opener + 1:].split(" ")[0] not in ADJUSTMENTS:
            break
        text = text[:opener - 1]
    call = (m.group(7) or "").strip()
    return int(m.group(1)), int(m.group(2)), m.group(3), text, call


ADJUSTMENTS = ("adopt", "never", "some", "ok", "err", "slice", "deref", "borrow",
               "borrow-var", "shared", "erase")


def call_fields(call):
    """(role, target, owner, inst) of a call record's text."""
    inner = groups(call)[0] if call else ""
    role = inner.split(" ")[0]
    rest = inner[len(role):].strip()
    owner = ""
    inst = []
    for g in groups(rest):
        if g.startswith("owner "):
            owner = g[len("owner "):]
        elif g.startswith("inst "):
            inst = split_top(g[len("inst "):])
    target = rest
    for marker in (" (owner ", " (inst ", " derived"):
        at = target.find(marker)
        if at >= 0:
            target = target[:at]
    if target.startswith("(owner") or target.startswith("(inst"):
        target = ""
    return role, target, owner, inst


def split_top(text):
    """The space-separated type spellings of an `inst` list."""
    out = []
    depth = 0
    start = 0
    for i, c in enumerate(text):
        if c in "(<[":
            depth += 1
        elif c in ")>]":
            depth -= 1
        elif c == " " and depth == 0 and i > start and text[i - 1] != ",":
            out.append(text[start:i])
            start = i + 1
    if start < len(text):
        out.append(text[start:])
    return out


def sawc2_answers(entry_rel):
    args = [build.SAWC2, "typecheck", "--dump"]
    for name, directory in build.STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, directory)]
    r = subprocess.run(args + [entry_rel], cwd=REPO, capture_output=True, text=True)
    fields = []
    tiers = []
    functions = []
    calls = []
    lets = []
    sources = {}
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
        if section == "bodies" and line.startswith("      ("):
            row = body_row(balanced(line.strip()))
            if row is not None:
                body_facts(current, row, calls, lets, sources)
            continue
        body = balanced(line.strip())
        # A function's phase-2 summary follows its signature, and the frozen
        # compiler has no counterpart to compare it with here.
        body = re.sub(r" \(summary .*\)\)$", ")", body)
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
    return fields, tiers, functions, calls, lets


def source_lines(path, sources):
    if path not in sources:
        with open(os.path.join(REPO, path), encoding="utf-8") as fh:
            sources[path] = fh.read().split("\n")
    return sources[path]


def body_facts(path, row, calls, lets, sources):
    """A `bodies` line's call, keyed as the frozen compiler's is, or its
    `let` binding."""
    line, col, kind, own, call = row
    if kind == "BindingName":
        # Only a `let` or `var` statement's binding: the frozen compiler
        # records an optional binding's elsewhere.
        text = source_lines(path, sources)[line - 1]
        name = re.match(r"\w+", text[col - 1:])
        before = text[:col - 1].split()
        statement = len(before) >= 1 and before[-1] in ("let", "var") and \
            (len(before) < 2 or before[-2] not in ("if", "guard", "while"))
        if name and statement:
            lets.append([path, line, name.group(0), normal(own)])
        return
    if not call:
        return
    role, target, owner, inst = call_fields(call)
    if role not in ("call", "memberwise", "case", "conversion"):
        return
    head = target.split("(")[0]
    name = head.split(".")[-1]
    if name == "init" or role == "memberwise":
        name = normal(owner).split("<")[0]
    module = ""
    if role == "call" and "." in head and not head.startswith(("Equatable.", "Printable.")):
        parts = head.split(".")
        module = "_".join(p for p in parts[:-1] if p and p[0].islower())
        # The frozen compiler names the entry module's functions with no
        # module; sawc2 names the entry module by its file.
        if "_" not in module and module == os.path.splitext(os.path.basename(path))[0]:
            module = ""
    first = ""
    params = target[len(head):]
    if params.startswith("("):
        leading = split_params(params[1:-1])[0]
        if ": " in leading:
            first = normal(leading.split(": ", 1)[1])
    calls.append([path, line, name, module, normal(owner), [normal(t) for t in inst], first])


def split_params(text):
    out = []
    depth = 0
    start = 0
    for i, c in enumerate(text):
        if c in "(<[":
            depth += 1
        elif c in ")>]":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(text[start:i].strip())
            start = i + 1
    out.append(text[start:].strip())
    return out


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
    fields, tiers, functions, calls, lets = sawc2_answers(entry_rel)
    their_fields = [[f, s, n, normal(t)] for f, s, n, t in frozen["fields"]]
    fa, fd = compare("field", their_fields, fields, lambda r: (r[0], r[1], r[2]), lambda r: r[3])
    their_tiers = [[f, n, "rule" if t == "abstract" else t] for f, n, t in frozen["tiers"]]
    ta, td = compare("tier", their_tiers, tiers, lambda r: (r[0], r[1]), lambda r: r[2])
    their_functions = [[f, l, n, [normal(p) for p in ps], normal(r)]
                       for f, l, n, ps, r in frozen["functions"]]
    sa, sd = compare("signature", their_functions, functions, lambda r: (r[0], r[1], r[2]),
                     lambda r: (tuple(r[3]), r[4]))
    their_lets = [[f, l, n, normal(t)] for f, l, n, t in frozen["lets"]]
    la, ld = compare("binding", their_lets, lets, lambda r: (r[0], r[1], r[2]), lambda r: r[3])
    body_diffs, body_counts = compare_calls(frozen["calls"], calls)
    for line in fd + td + sd + ld + body_diffs:
        print("DIFFERENCE: " + line)
    print("frozen check: %d field types agree, %d differ; %d signatures agree, %d differ; "
          "%d Copy tiers agree, %d differ" % (fa, len(fd), sa, len(sd), ta, len(td)))
    print("frozen check, bodies: %d binding types agree, %d differ; %s"
          % (la, len(ld), "; ".join("%s %d agree, %d differ" % (k, a, d)
                                     for k, a, d in body_counts)))
    return 1 if fd or td or sd or ld or body_diffs else 0


def strip_ref(text):
    for prefix in ("&var ", "&"):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def compare_calls(theirs, ours):
    """Each call aspect both compilers record, compared per (file, line,
    callee) as a multiset: the receiver's type, the type arguments, the
    overload an overloaded method's first parameter names, and the module a
    free function comes from."""
    skipped = ("[]", "__lend_var_[]", "get")
    t_owner = collections.defaultdict(list)
    t_inst = collections.defaultdict(list)
    t_first = collections.defaultdict(list)
    t_module = collections.defaultdict(list)
    for rel, line, name, symbol, receiver, targs in theirs:
        key = (rel, line, name)
        if name in skipped:
            continue
        if receiver:
            t_owner[key].append(normal(strip_ref(receiver)))
        if targs:
            t_inst[key].append(", ".join(normal(t) for t in targs if t != "GlobalAllocator"))
        if "$OL$" in symbol:
            t_first[key].append(normal(symbol.split("$OL$", 1)[1]))
        if "$m$" in symbol:
            t_module[key].append(symbol.split("$m$", 1)[1])
    o_owner = collections.defaultdict(list)
    o_inst = collections.defaultdict(list)
    o_first = collections.defaultdict(list)
    o_module = collections.defaultdict(list)
    for rel, line, name, module, owner, inst, first in ours:
        key = (rel, line, name)
        if owner:
            o_owner[key].append(owner)
            args = owner[owner.find("<") + 1:-1] if "<" in owner else ""
            if args and not inst:
                o_inst[key].append(args)
        if inst:
            o_inst[key].append(", ".join(inst))
        o_first[key].append(first)
        o_module[key].append(module)
    diffs = []
    counts = []
    for label, a, b, strict in (("receiver", t_owner, o_owner, False),
                                ("instantiation", t_inst, o_inst, False),
                                ("overload", t_first, o_first, False),
                                ("module", t_module, o_module, False)):
        agree = 0
        differ = 0
        for key in sorted(a, key=str):
            mine = sorted(b.get(key, []))
            for value in sorted(a[key]):
                if value in mine:
                    mine.remove(value)
                    agree += 1
                else:
                    differ += 1
                    diffs.append("%s %s: frozen %s, sawc2 %s"
                                 % (label, key, value, sorted(b.get(key, [])) or "nothing"))
        counts.append((label, agree, differ))
    return diffs, counts


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
