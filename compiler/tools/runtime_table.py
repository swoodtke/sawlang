#!/usr/bin/env python3
"""The runtime ABI table sawc2 checks a runtime against, made from Stage 0's.

    python compiler/tools/runtime_table.py          # fails if the table is stale
    python compiler/tools/runtime_table.py --write  # rewrites it

`sawc/runtime_abi.py` holds the frozen `__saw_rt_*` symbol set and reads each
seam's signature out of `sawc/rt/ABI.md` as machine classes (`word`, `i64`,
`i32`, `void`, `noreturn`). This writes the same rows into
`compiler/typecheck/src/runtimeabi.saw`, so the table sawc2 compiles in
outlives Stage 0 (SL:open-questions D41). Beside each seam goes its owner: the
program, for the argument accessors the compiler emits into every program
(ABI.md, "Program arguments"), else the runtime.

Per host it also records the runtime's sources, every `.saw` file of
`sawc/rt/common/` and the host's directory, and the seams `sawc/rt/shim.c`
defines for that host, read from the C source under its `__linux__` and
`__APPLE__` conditionals. `sawc2 runtime` compiles exactly those sources and
requires their exports and the shim's seams to be the runtime's seams, each
once; this tool requires the same of the sources' `@export` spellings, so the
table cannot describe a runtime the tree does not hold.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SAWC = os.path.join(REPO, "sawc")
RT = os.path.join(SAWC, "rt")
SHIM = os.path.join(RT, "shim.c")
SAW_FILE = os.path.join(REPO, "compiler", "typecheck", "src", "runtimeabi.saw")

# The seams the program defines, which a runtime must not (ABI.md, "Program
# arguments").
PROGRAM_SEAMS = ("__saw_rt_get_argc", "__saw_rt_get_argv")

# (sawc2 target, its runtime directory under sawc/rt, the C macro its clang
# defines and the one it does not).
HOSTS = (
    ("arm64-apple-darwin", "host_macos", "__APPLE__", "__linux__"),
    ("x86_64-unknown-linux-gnu", "host_linux", "__linux__", "__APPLE__"),
)

_EXPORT = re.compile(r'^\s*@export\("(__saw_rt_[A-Za-z0-9_]+)"\)')
_C_HEAD = re.compile(r"^[A-Za-z_][A-Za-z0-9_\s\*]*?\b(__saw_rt_[A-Za-z0-9_]+)\s*\(")


def abi_rows():
    """[(seam, param classes, result class, owner)], sorted by seam."""
    sys.path.insert(0, SAWC)
    import runtime_abi  # noqa: E402
    signatures = runtime_abi.abi_signatures()
    rows = []
    missing = []
    for name in sorted(runtime_abi.RUNTIME_ABI_SYMBOLS):
        sig = signatures.get(name)
        if sig is None:
            missing.append(name)
            continue
        params, result = sig
        owner = "program" if name in PROGRAM_SEAMS else "runtime"
        rows.append((name, ", ".join(params), result, owner))
    return rows, missing


def host_sources(directory):
    """The runtime's `.saw` sources for a host, relative to sawc/rt, sorted
    within each directory, common first."""
    out = []
    for sub in ("common", directory):
        names = sorted(n for n in os.listdir(os.path.join(RT, sub)) if n.endswith(".saw"))
        out += ["%s/%s" % (sub, n) for n in names]
    return out


def shim_seams(defined, undefined):
    """The `__saw_rt_*` functions shim.c defines when `defined` is a macro and
    `undefined` is not; any other conditional around a definition is an error,
    since its branch is not known here. Returns (seams, errors)."""
    with open(SHIM) as fh:
        lines = fh.read().split("\n")
    stack = []
    seams = []
    errors = []
    k = 0
    while k < len(lines):
        line = lines[k]
        directive = line.strip()
        if directive.startswith("#ifdef ") or directive.startswith("#ifndef "):
            word, macro = directive.split(None, 1)
            macro = macro.strip()
            if macro in (defined, undefined):
                value = (macro == defined) == (word == "#ifdef")
                stack.append(value)
            else:
                stack.append(None)
        elif directive.startswith("#if "):
            stack.append(None)
        elif directive.startswith("#else"):
            if stack and stack[-1] is not None:
                stack[-1] = not stack[-1]
        elif directive.startswith("#endif"):
            if stack:
                stack.pop()
        else:
            m = _C_HEAD.match(line)
            if m:
                end = k
                text = line
                while "{" not in text and ";" not in text and end + 1 < len(lines):
                    end += 1
                    text += lines[end]
                if "{" in text and ("{" if ";" not in text else min(("{", ";"), key=text.index)) == "{":
                    if None in stack:
                        errors.append("shim.c:%d: `%s` is defined under a conditional this tool does "
                                      "not read" % (k + 1, m.group(1)))
                    elif all(stack):
                        seams.append(m.group(1))
        k += 1
    return sorted(seams), errors


def source_exports(rel):
    out = []
    with open(os.path.join(RT, rel)) as fh:
        for line in fh:
            m = _EXPORT.match(line)
            if m:
                out.append(m.group(1))
    return out


def consistency(rows):
    """Failures of the tree against the table: each host's sources and shim
    export the runtime's seams exactly once."""
    failures = []
    runtime = set(name for name, _, _, owner in rows if owner == "runtime")
    for target, directory, defined, undefined in HOSTS:
        seams, errors = shim_seams(defined, undefined)
        failures += ["runtime table: %s" % e for e in errors]
        seen = {}
        for name in seams:
            seen.setdefault(name, []).append("shim.c")
        for rel in host_sources(directory):
            for name in source_exports(rel):
                seen.setdefault(name, []).append(rel)
        for name in sorted(seen):
            if name not in runtime:
                failures.append("runtime table: %s's runtime exports `%s`, which is not a runtime seam"
                                % (target, name))
            elif len(seen[name]) > 1:
                failures.append("runtime table: %s's runtime exports `%s` more than once (%s)"
                                % (target, name, ", ".join(seen[name])))
        for name in sorted(runtime - set(seen)):
            failures.append("runtime table: %s's runtime does not export `%s`" % (target, name))
    return failures


def saw_text(rows):
    out = []
    out.append("// The runtime ABI table (sawc/rt/ABI.md, as sawc/runtime_abi.py reads it), compiled\n")
    out.append("// in: written by compiler/tools/runtime_table.py --write, never by hand.\n")
    out.append("\n")
    out.append("// Each seam's name, its parameters' machine classes separated by commas, its\n")
    out.append("// result's class, and whether the runtime or the program defines it.\n")
    out.append("public func tc_runtime_abi_rows(names: &var Vector<String>, params: &var Vector<String>,\n")
    out.append("                                results: &var Vector<String>, owners: &var Vector<String>) {\n")
    for name, params, result, owner in rows:
        out.append('    tc_abi_row(&var names, &var params, &var results, &var owners, "%s", "%s", "%s", "%s")\n'
                   % (name, params, result, owner))
    out.append("}\n")
    out.append("\n")
    out.append("// A host's runtime sources, relative to the runtime root, in build order.\n")
    out.append("public func tc_runtime_sources(host: String) -> Vector<String> {\n")
    out.append("    var out = Vector<String>()\n")
    for target, directory, _, _ in HOSTS:
        out.append('    if host.equals("%s") {\n' % target)
        for rel in host_sources(directory):
            out.append('        try! out.push("%s")\n' % rel)
        out.append("    }\n")
    out.append("    move out\n")
    out.append("}\n")
    out.append("\n")
    out.append("// The seams a host's C shim defines.\n")
    out.append("public func tc_runtime_shim_seams(host: String) -> Vector<String> {\n")
    out.append("    var out = Vector<String>()\n")
    for target, _, defined, undefined in HOSTS:
        seams, _ = shim_seams(defined, undefined)
        out.append('    if host.equals("%s") {\n' % target)
        for name in seams:
            out.append('        try! out.push("%s")\n' % name)
        out.append("    }\n")
    out.append("    move out\n")
    out.append("}\n")
    out.append("\n")
    out.append("func tc_abi_row(names: &var Vector<String>, params: &var Vector<String>, results: &var Vector<String>,\n")
    out.append("                owners: &var Vector<String>, name: String, param: String, result: String, owner: String) {\n")
    out.append("    try! names.push(name)\n")
    out.append("    try! params.push(param)\n")
    out.append("    try! results.push(result)\n")
    out.append("    try! owners.push(owner)\n")
    out.append("}\n")
    return "".join(out)


def check():
    """(failures, counts): the Saw table against a fresh reading, and the
    tree against the table."""
    rows, missing = abi_rows()
    failures = ["runtime table: `%s` has no signature in sawc/rt/ABI.md" % name for name in missing]
    failures += consistency(rows)
    try:
        with open(SAW_FILE) as fh:
            current = fh.read()
    except OSError:
        current = None
    if current != saw_text(rows):
        failures.append("runtime table: %s is stale; rerun compiler/tools/runtime_table.py --write and "
                        "review the difference" % os.path.relpath(SAW_FILE, REPO))
    return failures, {"runtime ABI seams": len(rows)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    if args.write:
        rows, missing = abi_rows()
        for failure in ["`%s` has no signature" % m for m in missing] + consistency(rows):
            print(failure)
        with open(SAW_FILE, "w") as fh:
            fh.write(saw_text(rows))
        print("runtime table: %d seams written" % len(rows))
        return 0
    failures, counts = check()
    for failure in failures:
        print(failure)
    print("runtime table: %s (%d seams)" % ("FAIL" if failures else "ok", counts["runtime ABI seams"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
