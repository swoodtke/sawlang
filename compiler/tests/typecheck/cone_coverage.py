#!/usr/bin/env python3
"""How much of the std cone `sawc2 typecheck` gives a fully bound signature.

    python compiler/tests/typecheck/cone_coverage.py

Reads `compiler/tools/std_cone.txt`, typechecks the sawc2 build with the std
and builtin modules dumped too (`--interfaces`), and each runtime file the cone
names as a program of its own, since the runtime is built apart, and finds
each cone declaration's signature there. A declaration is covered when its
signature names no error type. The rest are listed with the reason: a runtime
file that does not load, a std file the parser refuses, a declaration missing
from its module, or an error type, with the notes. For information; nothing
gates on it.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402

CONE = os.path.join(COMPILER, "tools", "std_cone.txt")
KINDS = {"struct": "struct", "enum": "enum", "trait": "trait", "extern": "extern",
         "func": "func", "static": "static", "init": "init", "method": "method",
         "static-method": "method", "type": "alias"}


def cone_entries():
    """(module, kind, path, labels or None) for each cone declaration."""
    out = []
    module = None
    for line in open(CONE):
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\S.*): \d+$", line)
        if m:
            module = m.group(1)
            continue
        if line.startswith("    "):
            continue
        body = line.strip().replace("  via runtime", "")
        kind, _, rest = body.partition(" ")
        labels = None
        if "(" in rest:
            rest, _, inside = rest.partition("(")
            inside = inside.rstrip(")")
            labels = [p.split(":")[0].strip() for p in inside.split(",") if p.strip()]
        out.append((module, kind, rest.strip(), labels))
    return out


def params_of(line):
    """The parameter names of a dumped signature line."""
    at = line.find("(params")
    if at < 0:
        return []
    i = at + len("(params")
    names = []
    depth = 0
    start = None
    while i < len(line):
        c = line[i]
        if c == "(":
            depth += 1
            if depth == 1:
                start = i + 1
        elif c == ")":
            if depth == 0:
                break
            depth -= 1
            if depth == 0 and start is not None:
                names.append(line[start:i].split(" ")[0])
        i += 1
    return names


def dumped(output):
    """{module: [declaration lines]} and {module: [member lines]}."""
    decls = {}
    members = {}
    module = None
    section = None
    for line in output.split("\n"):
        if line.startswith("(Module "):
            module = line[len("(Module "):].strip()
            decls[module] = []
            members[module] = []
        elif line.startswith("  ("):
            section = line.strip("( )")
        elif module is not None and section == "declarations" and line.startswith("    ("):
            decls[module].append(line.strip())
        elif module is not None and section == "members":
            members[module].append(line.strip())
    return decls, members


def main():
    args = ["--dump", "--interfaces", "--notes"]
    for name, directory in build.STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, directory)]
    entry = os.path.relpath(build.DRIVER_ENTRY, REPO)
    r = subprocess.run([build.SAWC2, "typecheck"] + args + [entry], cwd=REPO,
                       capture_output=True, text=True)
    decls, members = dumped(r.stdout)
    # The runtime's modules are built apart, each file its own program, so
    # each is checked as an entry of its own and filed under its identity.
    runtime = sorted({m for m, _, _, _ in cone_entries() if m.startswith("rt.")})
    for module in runtime:
        path = os.path.join("sawc", *module.split(".")) + ".saw"
        rr = subprocess.run([build.SAWC2, "typecheck", "--dump", path], cwd=REPO,
                            capture_output=True, text=True)
        more, more_members = dumped(rr.stdout)
        base = module.split(".")[-1]
        if base in more:
            decls[module] = more[base]
            members[module] = more_members[base]
        r = subprocess.CompletedProcess(r.args, r.returncode, r.stdout + rr.stdout, r.stderr)
    notes = [l for l in r.stdout.split("\n") if l.startswith("NOTE\t")]
    covered = 0
    outside = []
    unavailable = []
    missing = []
    erroneous = []
    for module, kind, path, labels in cone_entries():
        if module.startswith("("):
            continue
        if module not in decls:
            if module.startswith("rt."):
                outside.append("%s %s (%s)" % (kind, path, module))
            else:
                unavailable.append("%s %s (%s)" % (kind, path, module))
            continue
        found = None
        if kind == "synthesized":
            owner, _, member = path.partition(".")
            for line in members[module]:
                if line.startswith("(method %s " % member) and "(synthesized" in line:
                    found = line
        else:
            want = KINDS.get(kind, kind)
            for line in decls[module]:
                head = "(%s %s " % (want, path)
                if not line.startswith(head):
                    continue
                if kind == "static-method" and not line.rstrip(")").endswith("static"):
                    if " static)" not in line and " static " not in line:
                        continue
                if labels is not None and params_of(line) != labels:
                    continue
                found = line
                break
        if found is None:
            missing.append("%s %s (%s)" % (kind, path, module))
        elif "(error)" in found:
            erroneous.append("%s %s (%s)" % (kind, path, module))
        else:
            covered += 1
    total = covered + len(outside) + len(unavailable) + len(missing) + len(erroneous)
    print("std cone coverage: %d of %d declarations have fully bound signatures" % (covered, total))
    print("in a runtime file that does not load: %d" % len(outside))
    for item in outside:
        print("  " + item)
    print("in a std module the parser refuses: %d" % len(unavailable))
    for item in unavailable:
        print("  " + item)
    print("missing from their module: %d" % len(missing))
    for item in missing:
        print("  " + item)
    print("with an error type: %d" % len(erroneous))
    for item in erroneous:
        print("  " + item)
    print("notes: %d" % len(notes))
    for note in notes:
        print("  " + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
