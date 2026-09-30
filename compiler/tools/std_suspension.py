#!/usr/bin/env python3
"""The suspension verdict of every std function, as Stage 0 decides it.

    python compiler/tools/std_suspension.py          # fails if the table is stale
    python compiler/tools/std_suspension.py --write  # rewrites the table and its Saw form

sawc2 reads std as interfaces and checks no std body, so its phase 2 cannot
infer whether a std function suspends. Until the new std's bodies are checked,
it takes each std function's verdict from this table: the frozen compiler's
own std check, observed in a child process with `sawc/` never edited, and the
one suspension analysis that check runs over std's effect graph (the analysis
Stage 0's std censuses read). Each free function, extension method and trait
default body of `sawc/builtin.saw` and `sawc/std` gets one row:

- `suspends`: the body owns a suspension a frame is built around;
- `nonsync`: it only may suspend, as a call through a non-`sync` function
  value does, so it is not sync-callable but frames nothing;
- `sync`: neither.

A row is keyed as sawc2 names the declaration: its module, its path, and its
parameters' names, `self` left out. Overloads sharing a key take the worst
verdict. `std_suspension.txt` is the record; `compiler/typecheck/src/
stdsuspension.saw` is the same rows compiled into sawc2.

The check also derives, from the source alone, the std modules whose bodies
spell a parking primitive, closed over the std modules that import them, and
requires that set to equal the modules holding a `suspends` row.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SAWC = os.path.join(REPO, "sawc")
TABLE_FILE = os.path.join(HERE, "std_suspension.txt")
SAW_FILE = os.path.join(REPO, "compiler", "typecheck", "src", "stdsuspension.saw")
OBSERVE_FLAG = "--observe"
TIMEOUT = 600
VERDICTS = ("sync", "nonsync", "suspends")
SAW_CODES = {"sync": "TC_STD_SYNC", "nonsync": "TC_STD_NONSYNC", "suspends": "TC_STD_SUSPENDS"}
# The spellings a body parks with: the cooperative intrinsics, which no
# declaration writes. The executor's own `__saw_exec_*` helpers are not among
# them: the drive loop they serve is `sync`, so naming one parks nothing.
PARK_SPELLINGS = re.compile(
    r"\b(?:yield_now|io_wait|io_wait_until|__saw_io_park|__saw_chan_park)\b|\bsleep\(")
_IMPORT = re.compile(r"^\s*import\s+std\.([a-z_][a-z0-9_.]*?)(?:\.\{|\.\*|\s|$)")
_IDENTITY_SUFFIX = "$m$"


def module_of(path):
    """`builtin`, `std.vector`, `std.compiler.frame`; None outside sawc/'s std."""
    rel = os.path.relpath(os.path.abspath(path or ""), SAWC).replace(os.sep, "/")
    if rel == "builtin.saw":
        return "builtin"
    if rel.startswith("std/") and rel.endswith(".saw"):
        return "std." + rel[len("std/"):-len(".saw")].replace("/", ".")
    return None


def written_name(identity):
    return (identity or "").split(_IDENTITY_SUFFIX)[0]


# The parameters the frozen parser's place lowering adds to a `borrows`
# accessor, which its source does not write.
LOWERED_PARAMETERS = ("self", "__window", "__absent")
# The prefix of the exclusive twin that lowering synthesizes for an accessor.
LOWERED_TWIN = "__lend_var_"


def key_of(module, path, parameters):
    names = [p.name for p in parameters if p.name not in LOWERED_PARAMETERS]
    return "%s.%s(%s)" % (module, path, ", ".join(names))


# ---------------------------------------------------------------- the observer

def observe(out_path):
    """Runs in the child: the frozen std check, then one row per function."""
    sys.path.insert(0, SAWC)
    import sawc
    from errors import ErrorReporter
    from typechecker import TypeChecker
    from typechecker.effects import classify_suspensions, frame_boundary, might_suspend

    ast = sawc.load_builtins()
    # The declarations are listed before the check runs: it synthesizes
    # methods the source does not write (a policy's `deinit`, a default body
    # copied into each conformer, a place accessor's twin) and adds a window
    # parameter to each place accessor, and sawc2 sees none of that.
    written = []
    for fn in ast.functions:
        module = module_of(fn.source_file)
        if module is not None and not getattr(fn, "is_mono_instance", False):
            written.append((key_of(module, fn.name, fn.parameters), "fn", fn))
    for ext in ast.extensions:
        module = module_of(getattr(ext, "source_file", None))
        if module is None:
            continue
        owner = written_name(ext.struct_name)
        for m in ext.methods:
            if m.name.startswith(LOWERED_TWIN):
                continue
            written.append((key_of(module, "%s.%s" % (owner, m.name), m.parameters), "method", m))
    for trait in ast.traits:
        module = module_of(getattr(trait, "source_file", None))
        if module is None:
            continue
        for m in trait.methods:
            if getattr(m, "body", None) is not None:
                written.append((key_of(module, "%s.%s" % (written_name(trait.name), m.name),
                                       m.parameters), "method", m))

    tc = TypeChecker(ErrorReporter("", "builtins"))
    tc.namespace.allow_all_access = True
    tc._checking_builtins = True
    tc.free_function_owners = sawc.std_free_function_owner_census(ast)
    if not sawc.run_typecheck(tc, lambda: tc.check(ast, require_main=False)):
        raise SystemExit("the frozen compiler's std check failed")
    answers = classify_suspensions(tc._suspend_nodes)

    def verdict(key):
        causes = answers.causes(key)
        if frame_boundary(causes):
            return "suspends"
        if might_suspend(causes):
            return "nonsync"
        return "sync"

    rows = {}

    def add(key, v):
        old = rows.get(key)
        if old is None or VERDICTS.index(v) > VERDICTS.index(old):
            rows[key] = v

    for key, kind, decl in written:
        if kind == "fn":
            add(key, verdict(("fn", getattr(decl, "mangled_symbol", None) or decl.name)))
        else:
            add(key, verdict(decl.node_id))
    with open(out_path, "w") as fh:
        json.dump(rows, fh)


def observed_rows():
    """The rows, from a child process running the frozen compiler."""
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), OBSERVE_FLAG, out],
                           capture_output=True, text=True, timeout=TIMEOUT)
        if r.returncode != 0:
            raise RuntimeError("the observer failed: %s" % (r.stderr.strip() or r.stdout.strip()))
        with open(out) as fh:
            return json.load(fh)
    finally:
        os.unlink(out)


# ---------------------------------------------------------------- the records

HEADER = """\
# The suspension verdict of every std function, as Stage 0's std check decides
# it: `suspends` (a frame is built around it), `nonsync` (not sync-callable, and
# framing nothing) or `sync`. Written by compiler/tools/std_suspension.py
# --write; compiler/tests/run.py fails when it is stale. sawc2's phase 2 reads
# these rows, compiled in as compiler/typecheck/src/stdsuspension.saw, for the
# std functions whose bodies it does not check.
"""


def table_text(rows):
    lines = [HEADER]
    for key in sorted(rows):
        lines.append("%s\t%s\n" % (key, rows[key]))
    return "".join(lines)


def saw_text(rows):
    out = ["// The std suspension table (compiler/tools/std_suspension.txt), compiled in:\n",
           "// written by compiler/tools/std_suspension.py --write, never by hand.\n",
           "\n",
           "public static TC_STD_SYNC: Int = 0\n",
           "public static TC_STD_NONSYNC: Int = 1\n",
           "public static TC_STD_SUSPENDS: Int = 2\n",
           "\n",
           "// Each row's key, as `decl_identity` and the parameters' names spell it,\n",
           "// and its verdict.\n",
           "public func tc_std_suspension_rows(keys: &var Vector<String>, verdicts: &var Vector<Int>) {\n"]
    for key in sorted(rows):
        out.append("    tc_std_row(&var keys, &var verdicts, \"%s\", %s)\n" % (key, SAW_CODES[rows[key]]))
    out.append("}\n\n")
    out.append("func tc_std_row(keys: &var Vector<String>, verdicts: &var Vector<Int>, key: String, verdict: Int) {\n")
    out.append("    try! keys.push(key)\n")
    out.append("    try! verdicts.push(verdict)\n")
    out.append("}\n")
    return "".join(out)


def parking_modules():
    """The std modules whose non-comment source spells a parking primitive,
    closed over the std modules importing one of them."""
    sources = {}
    for root, dirs, files in os.walk(os.path.join(SAWC, "std")):
        dirs.sort()
        for name in sorted(files):
            if name.endswith(".saw"):
                path = os.path.join(root, name)
                with open(path) as fh:
                    sources[module_of(path)] = fh.read().splitlines()
    parks = set()
    imports = {}
    for module, lines in sources.items():
        imports[module] = set()
        for line in lines:
            code = line.split("//", 1)[0]
            if PARK_SPELLINGS.search(code):
                parks.add(module)
            m = _IMPORT.match(code)
            if m:
                imports[module].add("std." + m.group(1))
    changed = True
    while changed:
        changed = False
        for module, deps in imports.items():
            if module not in parks and deps & parks:
                parks.add(module)
                changed = True
    return parks


def check_rows(rows):
    """Failures of the rows' own consistency: the module cross-check and the
    wrapper pin."""
    failures = []
    holding = set()
    for key, v in rows.items():
        if v != "suspends":
            continue
        # The module is the longest leading run of the key's path that names
        # one: a method's key adds its type and its name.
        parts = key.split("(")[0].split(".")
        for cut in range(len(parts) - 1, 0, -1):
            candidate = ".".join(parts[:cut])
            if candidate in _known_modules():
                holding.add(candidate)
                break
    parks = parking_modules()
    for module in sorted(holding - parks):
        failures.append("std suspension: %s holds a `suspends` row, but no body of it spells a "
                        "parking primitive or imports a module that does" % module)
    for module in sorted(parks - holding):
        failures.append("std suspension: %s spells a parking primitive, or imports a module that "
                        "does, but holds no `suspends` row" % module)
    if rows.get("std.task.yield_now()") != "suspends":
        failures.append("std suspension: `std.task.yield_now()` must be `suspends`, and is %s"
                        % rows.get("std.task.yield_now()", "absent"))
    return failures


_MODULES = None


def _known_modules():
    global _MODULES
    if _MODULES is None:
        found = {"builtin"}
        for root, dirs, files in os.walk(os.path.join(SAWC, "std")):
            for name in files:
                if name.endswith(".saw"):
                    found.add(module_of(os.path.join(root, name)))
        _MODULES = found
    return _MODULES


def check():
    """(failures, counts): the table and its Saw form against a fresh
    observation, and the rows' consistency."""
    rows = observed_rows()
    failures = check_rows(rows)
    for path, text in ((TABLE_FILE, table_text(rows)), (SAW_FILE, saw_text(rows))):
        try:
            with open(path) as fh:
                current = fh.read()
        except OSError:
            current = None
        if current != text:
            failures.append("std suspension: %s is stale; rerun compiler/tools/std_suspension.py "
                            "--write and review the difference" % os.path.relpath(path, REPO))
    counts = {"std suspension rows": len(rows)}
    return failures, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(OBSERVE_FLAG, metavar="OUT")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    if args.observe:
        observe(args.observe)
        return 0
    if args.write:
        rows = observed_rows()
        for failure in check_rows(rows):
            print(failure)
        with open(TABLE_FILE, "w") as fh:
            fh.write(table_text(rows))
        with open(SAW_FILE, "w") as fh:
            fh.write(saw_text(rows))
        print("std suspension: %d rows written" % len(rows))
        return 0
    failures, counts = check()
    for failure in failures:
        print(failure)
    print("std suspension: %s (%d rows)" % ("FAIL" if failures else "ok", counts["std suspension rows"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
