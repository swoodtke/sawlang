#!/usr/bin/env python3
"""The runtime ABI table sawc2 checks a runtime against, read from `runtime/`.

    python compiler/tools/runtime_table.py          # fails if the table is stale
    python compiler/tools/runtime_table.py --write  # rewrites it

`sawc/runtime_abi.py` holds the frozen `__saw_rt_*` symbol set. This reads each
seam's signature out of `runtime/ABI.md` as machine classes (`word`, `i64`,
`i32`, `void`, `noreturn`) and writes the rows into
`compiler/typecheck/src/runtimeabi.saw`, so the table sawc2 compiles in
outlives Stage 0 (SL:open-questions D41). Beside each seam goes its owner: the
program, for the argument accessors the compiler emits into every program
(ABI.md, "Program arguments"), else the runtime.

Per host it also records the runtime's sources, every `.saw` file of
`runtime/common/` and the host's directory, and the seams `runtime/shim.c`
defines for that host, read from the C source under its `__linux__` and
`__APPLE__` conditionals. `sawc2 runtime` compiles exactly those sources and
requires their exports and the shim's seams to be the runtime's seams, each
once; this tool requires the same of the sources' `@export` spellings, so the
table cannot describe a runtime the tree does not hold.

Stage 0 builds its own copy, `sawc/rt/`, and links every program it builds
against it, the oracles' programs among them. The check requires that copy to be `runtime/` byte for byte, and Stage 0's reading
of its ABI.md to be this one, so a runtime change is made in both trees until
`sawc/` is deleted (`copy_drift`).
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SAWC = os.path.join(REPO, "sawc")
RT = os.path.join(REPO, "runtime")
ABI_DOC = os.path.join(RT, "ABI.md")
SHIM = os.path.join(RT, "shim.c")
STAGE0_RT = os.path.join(SAWC, "rt")
SAW_FILE = os.path.join(REPO, "compiler", "typecheck", "src", "runtimeabi.saw")

# The seams the program defines, which a runtime must not (ABI.md, "Program
# arguments").
PROGRAM_SEAMS = ("__saw_rt_get_argc", "__saw_rt_get_argv")

# (sawc2 target, its runtime directory under runtime/, the C macro its clang
# defines and the one it does not).
HOSTS = (
    ("arm64-apple-darwin", "host_macos", "__APPLE__", "__linux__"),
    ("x86_64-unknown-linux-gnu", "host_linux", "__linux__", "__APPLE__"),
    ("aarch64-unknown-linux-gnu", "host_linux", "__linux__", "__APPLE__"),
)

_EXPORT = re.compile(r'^\s*@export\("(__saw_rt_[A-Za-z0-9_]+)"\)')
_C_HEAD = re.compile(r"^[A-Za-z_][A-Za-z0-9_\s\*]*?\b(__saw_rt_[A-Za-z0-9_]+)\s*\(")

# A signature inside backticks, `name(params) -> result`, whose result may
# carry a parenthesized gloss (`-> word  (0/-1)`).
_SIGNATURE = re.compile(r"`(__saw_rt_[A-Za-z0-9_]+)\(([^`]*)\)\s*->\s*([^`]+)`")

# ABI.md's type spellings, as the machine class the C ABI distinguishes. Every
# pointer is pointer-width, so it is a `word`; `Int64` stays apart from `word`
# because the two differ on a 32-bit target.
ABI_CLASSES = {
    "void": "void",
    "!": "noreturn",
    "i32": "i32",
    "int64": "i64",
    "i64": "i64",
    "word": "word",
    "ptr": "word",
}


def stage0_abi():
    """Stage 0's `runtime_abi` module: the frozen symbol set, and its own
    reading of `sawc/rt/ABI.md`."""
    sys.path.insert(0, SAWC)
    import runtime_abi  # noqa: E402
    return runtime_abi


def abi_class(spelling):
    """The machine class of one ABI.md type spelling; an unknown spelling is
    returned as itself, lowercased, for the caller to refuse."""
    text = spelling.strip()
    if not text.startswith("void*"):
        text = text.split("(")[0].strip()
    if not text:
        return "void"
    if text.endswith("*") or text.startswith("void*"):
        return "word"
    return ABI_CLASSES.get(text.lower(), text.lower())


def abi_signatures(path=ABI_DOC):
    """{seam: (param classes, result class)} read out of the ABI document at
    `path`. A seam the document gives twice keeps its first signature."""
    with open(path) as fh:
        text = fh.read()
    found = {}
    for m in _SIGNATURE.finditer(text):
        name = m.group(1)
        if name in found:
            continue
        params = []
        for part in m.group(2).split(","):
            part = part.strip()
            if part:
                params.append(abi_class(part.split(":", 1)[1] if ":" in part else part))
        found[name] = (tuple(params), abi_class(m.group(3)))
    return found


def copy_drift():
    """Every way Stage 0's copy of the runtime differs from `runtime/`, file by
    file, and how many files `runtime/` holds. The oracles compare programs
    Stage 0 links against its copy with programs sawc2 links against the one
    Stage 1 builds from `runtime/`, so both must be one runtime."""
    def files(root):
        out = {}
        for directory, subdirs, names in os.walk(root):
            subdirs.sort()
            for name in names:
                path = os.path.join(directory, name)
                out[os.path.relpath(path, root)] = path
        return out
    if not os.path.isdir(STAGE0_RT):
        return ["runtime table: Stage 0's copy of the runtime, %s, is missing" % os.path.relpath(STAGE0_RT, REPO)], 0
    ours, theirs = files(RT), files(STAGE0_RT)
    failures = []
    for rel in sorted(set(ours) | set(theirs)):
        if rel not in theirs:
            failures.append("runtime table: runtime/%s has no copy in sawc/rt/" % rel)
        elif rel not in ours:
            failures.append("runtime table: sawc/rt/%s has no copy in runtime/" % rel)
        else:
            with open(ours[rel], "rb") as a, open(theirs[rel], "rb") as b:
                if a.read() != b.read():
                    failures.append("runtime table: runtime/%s and sawc/rt/%s differ; Stage 0 links its copy "
                                    "into Stage 1, so a runtime change is made in both" % (rel, rel))
    return failures, len(ours)


def abi_rows():
    """[(seam, param classes, result class, owner)], sorted by seam."""
    runtime_abi = stage0_abi()
    signatures = abi_signatures()
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
    """The runtime's `.saw` sources for a host, relative to runtime/, sorted
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
    out.append("// The runtime ABI table (runtime/ABI.md, as compiler/tools/runtime_table.py reads it),\n")
    out.append("// compiled in: written by that tool's --write, never by hand.\n")
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
    """(failures, counts): the Saw table against a fresh reading, the tree
    against the table, and Stage 0's copy of the runtime against `runtime/`."""
    rows, missing = abi_rows()
    failures = ["runtime table: `%s` has no signature in runtime/ABI.md" % name for name in missing]
    failures += consistency(rows)
    drift, compared = copy_drift()
    failures += drift
    if not drift and abi_signatures() != stage0_abi().abi_signatures():
        failures.append("runtime table: this tool and sawc/runtime_abi.py read the same ABI.md differently")
    try:
        with open(SAW_FILE) as fh:
            current = fh.read()
    except OSError:
        current = None
    if current != saw_text(rows):
        failures.append("runtime table: %s is stale; rerun compiler/tools/runtime_table.py --write and "
                        "review the difference" % os.path.relpath(SAW_FILE, REPO))
    return failures, {"runtime ABI seams": len(rows), "runtime files Stage 0's copy matches": compared}


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
