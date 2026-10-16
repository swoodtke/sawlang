#!/usr/bin/env python3
"""The suspension verdict of every std function, as Stage 0 decides it.

    python compiler/tools/std_suspension.py          # fails if the Saw form is not the table's
    python compiler/tools/std_suspension.py --write  # observes Stage 0, rewrites both

sawc2 reads std as interfaces and checks no std body, so its phase 2 cannot
infer whether a std function suspends. Until the new std's bodies are checked,
it takes each std function's verdict from this table, a recorded snapshot:
the frozen compiler's own std check, observed by `--write` in a child process
run by the v0 compiler's checkout (`oracle.v0_root`), and the one suspension
analysis that check runs over std's effect graph (the analysis Stage 0's std
censuses read). Each free function, extension method and trait default body
of that checkout's `sawc/builtin.saw` and `sawc/std` gets one row:

- `suspends`: the body owns a suspension a frame is built around;
- `nonsync`: it only may suspend, as a call through a non-`sync` function
  value does, so it is not sync-callable but frames nothing;
- `sync`: neither.

A row that may suspend also carries its cause set, the kinds of suspension
source that reach it (`cooperative`, `blocking`, `test_suspend`,
`existential_dispatch`, `closure_call`, `unclassified`), and the label of the
first source that is not `blocking`, as Stage 0's diagnostic path names it:
a `Thread.spawn` body permits the `blocking` cause alone, and its refusal
names what it struck on (`io_wait`).

A row is keyed as sawc2 names the declaration: its module, its path, and its
parameters' names, `self` left out. Overloads sharing a key take the worst
verdict and the union of their causes. `std_suspension.txt` is the record, with the triple it was observed
on; `compiler/typecheck/src/stdsuspension.saw` is the same rows compiled into
sawc2, and the check holds the two equal.

`--write` also derives, from the source alone, the std modules whose bodies
spell a parking primitive, closed over the std modules that import them, and
refuses to write unless that set equals the modules holding a `suspends` row.
The new std in `std/` needs no table, since sawc2 checks its bodies, and the
check gives it the same cross-check: the modules spelling one of its park
points (`std.task`'s lang items), closed over their importers, against the
modules holding a function sawc2's summaries say suspends.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import build  # noqa: E402
# The v0 checkout's `sawc/`, whose std the table describes; `use_v0_checkout`
# sets it, and only `--write` and the observer read it.
SAWC = None
TABLE_FILE = os.path.join(HERE, "std_suspension.txt")
SAW_FILE = os.path.join(REPO, "compiler", "typecheck", "src", "stdsuspension.saw")
OBSERVE_FLAG = "--observe"
TIMEOUT = 600
VERDICTS = ("sync", "nonsync", "suspends")
SAW_CODES = {"sync": "TC_STD_SYNC", "nonsync": "TC_STD_NONSYNC", "suspends": "TC_STD_SUSPENDS"}
# Stage 0's cause bits, by the names its `SuspendCause.NAMES` gives them; the
# Saw form writes the bits, which sawc2's `TC_CAUSE_*` constants share.
CAUSE_BITS = (("cooperative", 1), ("blocking", 2), ("test_suspend", 4),
              ("existential_dispatch", 8), ("closure_call", 16), ("unclassified", 32))
BLOCKING_BIT = 2
NONE = "-"
# Stage 0's `PATH_PLACEHOLDER_LABEL`: a path that found no source.
PLACEHOLDER_LABEL = "<suspension source>"
# The spellings a body parks with: the cooperative intrinsics, which no
# declaration writes. The executor's own `__saw_exec_*` helpers are not among
# them: the drive loop they serve is `sync`, so naming one parks nothing.
PARK_SPELLINGS = re.compile(
    r"\b(?:yield_now|io_wait|io_wait_until|__saw_io_park|__saw_chan_park)\b|\bsleep\(")
_IMPORT = re.compile(r"^\s*import\s+std\.([a-z_][a-z0-9_.]*?)(?:\.\{|\.\*|\s|$)")
_IDENTITY_SUFFIX = "$m$"
# The new std's park points, the lang items `std/task.saw` declares; a
# body parks by calling one.
NEW_STD = os.path.join(REPO, "std")
NEW_PARK_SPELLINGS = re.compile(r"\b__saw_park_\w+\(")
# The program whose check covers every new-std module, with the summaries.
NEW_STD_ENTRY = os.path.join(REPO, "compiler", "tests", "std", "entry.saw")


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
    use_v0_checkout()
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

    def verdict(causes):
        if frame_boundary(causes):
            return "suspends"
        if might_suspend(causes):
            return "nonsync"
        return "sync"

    def label(node_key, causes):
        """The first non-`blocking` source's label on the diagnostic path."""
        node = tc._suspend_nodes.get(node_key)
        if node is None or not causes & ~BLOCKING_BIT:
            return ""
        hops, _, _ = tc._effect_path(node, skip_blocking=True)
        return hops[-1]

    rows = {}

    def add(key, node_key):
        causes = answers.causes(node_key)
        v = verdict(causes)
        old = rows.get(key)
        if old is None:
            rows[key] = [v, causes, label(node_key, causes)]
            return
        if VERDICTS.index(v) > VERDICTS.index(old[0]):
            old[0] = v
        old[1] |= causes
        if not old[2]:
            old[2] = label(node_key, causes)

    for key, kind, decl in written:
        if kind == "fn":
            add(key, ("fn", getattr(decl, "mangled_symbol", None) or decl.name))
        else:
            add(key, decl.node_id)
    with open(out_path, "w") as fh:
        json.dump(rows, fh)


def use_v0_checkout():
    """Points `SAWC` at the v0 compiler's checkout (`oracle.v0_root`), whose
    std the observation reads and whose own sources the rows are checked
    against; only `--write` and the observer need it."""
    global SAWC, _MODULES
    sys.path.insert(0, os.path.join(REPO, "compiler", "tests"))
    import oracle
    SAWC = os.path.join(oracle.v0_root(), "sawc")
    _MODULES = None
    return oracle


def observed_rows():
    """The rows, from a child process running the v0 compiler's std check
    with its checkout's venv."""
    oracle = use_v0_checkout()
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        r = subprocess.run([oracle.v0_python(), os.path.abspath(__file__), OBSERVE_FLAG, out],
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
# framing nothing) or `sync`; then its cause set and the label of its first
# source that is not `blocking`, `-` for none. Written by
# compiler/tools/std_suspension.py --write through the v0 compiler;
# compiler/tests/run.py fails when the Saw form differs. sawc2's phase 2 reads
# these rows, compiled in as compiler/typecheck/src/stdsuspension.saw, for the
# std functions whose bodies it does not check.
"""
_TRIPLE = "# observed on "


def causes_text(bits):
    named = [name for name, bit in CAUSE_BITS if bits & bit]
    return ",".join(named) if named else NONE


def causes_bits(text):
    if text == NONE:
        return 0
    by_name = dict(CAUSE_BITS)
    return sum(by_name[name] for name in text.split(","))


def table_text(rows, triple):
    lines = [HEADER, "%s%s\n" % (_TRIPLE, triple)]
    for key in sorted(rows):
        verdict, bits, label = rows[key]
        lines.append("%s\t%s\t%s\t%s\n" % (key, verdict, causes_text(bits), label or NONE))
    return "".join(lines)


def read_table():
    """(the recorded rows, the triple Stage 0 observed them on); each row is
    [verdict, cause bits, label]."""
    rows = {}
    triple = None
    with open(TABLE_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(_TRIPLE):
                triple = line[len(_TRIPLE):]
            elif line and not line.startswith("#"):
                key, verdict, causes, label = line.split("\t")
                rows[key] = [verdict, causes_bits(causes), "" if label == NONE else label]
    return rows, triple


def saw_text(rows):
    out = ["// The std suspension table (compiler/tools/std_suspension.txt), compiled in:\n",
           "// written by compiler/tools/std_suspension.py --write, never by hand.\n",
           "\n",
           "public static TC_STD_SYNC: Int = 0\n",
           "public static TC_STD_NONSYNC: Int = 1\n",
           "public static TC_STD_SUSPENDS: Int = 2\n",
           "\n",
           "// Each row's key, as `decl_identity` and the parameters' names spell it,\n",
           "// its verdict, its cause bits (`TC_CAUSE_*`) and the label of its first\n",
           "// source that is not `blocking`, \"\" for none.\n",
           "public func tc_std_suspension_rows(rows: &var TcStdRows) {\n"]
    for key in sorted(rows):
        verdict, bits, label = rows[key]
        out.append("    tc_std_row(&var rows, \"%s\", %s, %d, \"%s\")\n"
                   % (key, SAW_CODES[verdict], bits, label))
    out.append("}\n\n")
    out.append("// The table's columns, one entry per row in each.\n")
    out.append("public struct TcStdRows {\n")
    out.append("    keys: Vector<String>\n")
    out.append("    verdicts: Vector<Int>\n")
    out.append("    causes: Vector<Int>\n")
    out.append("    labels: Vector<String>\n")
    out.append("}\n\n")
    out.append("extension TcStdRows: NoCopy {}\n\n")
    out.append("func tc_std_row(rows: &var TcStdRows, key: String, verdict: Int, causes: Int, "
               "label: String) {\n")
    out.append("    try! rows.keys.push(key)\n")
    out.append("    try! rows.verdicts.push(verdict)\n")
    out.append("    try! rows.causes.push(causes)\n")
    out.append("    try! rows.labels.push(label)\n")
    out.append("}\n")
    return "".join(out)


def new_module_of(path):
    """`std.task`, `std.compiler.frame`: a module of the new std, by its file."""
    rel = os.path.relpath(os.path.abspath(path), NEW_STD).replace(os.sep, "/")
    return "std." + rel[:-len(".saw")].replace("/", ".")


def parking_modules(std_dir=None, spellings=PARK_SPELLINGS, module_name=module_of):
    """The std modules under `std_dir`, Stage 0's by default, whose
    non-comment source spells a parking primitive, closed over the std
    modules importing one of them."""
    sources = {}
    for root, dirs, files in os.walk(std_dir or os.path.join(SAWC, "std")):
        dirs.sort()
        for name in sorted(files):
            if name.endswith(".saw"):
                path = os.path.join(root, name)
                with open(path) as fh:
                    sources[module_name(path)] = fh.read().splitlines()
    parks = set()
    imports = {}
    for module, lines in sources.items():
        imports[module] = set()
        for line in lines:
            code = line.split("//", 1)[0]
            if spellings.search(code):
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
    for key, (v, bits, label) in rows.items():
        if label == PLACEHOLDER_LABEL:
            failures.append("std suspension: %s's diagnostic path reaches no source" % key)
        if bits & ~BLOCKING_BIT and not label:
            failures.append("std suspension: %s may suspend by a cause other than `blocking`, and "
                            "its row names no source" % key)
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
    yield_row = rows.get("std.task.yield_now()")
    if yield_row is None or yield_row[0] != "suspends":
        failures.append("std suspension: `std.task.yield_now()` must be `suspends`, and is %s"
                        % (yield_row[0] if yield_row else "absent"))
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


def new_std_suspending_modules(sawc2):
    """The new-std modules holding a function sawc2's summaries say suspends,
    or None with the reason the check could not run."""
    if not os.path.exists(sawc2):
        return None, "%s is not built" % os.path.relpath(sawc2, REPO)
    r = subprocess.run([sawc2, "typecheck", "--check", "--summaries", "--std-root", NEW_STD,
                        NEW_STD_ENTRY], capture_output=True, text=True, timeout=TIMEOUT, cwd=REPO)
    if r.returncode != 0:
        return None, "sawc2 refuses the new std: %s" % (r.stdout.strip() or r.stderr.strip())
    modules = {new_module_of(p) for p in glob.glob(os.path.join(NEW_STD, "**", "*.saw"),
                                                    recursive=True)}
    holding = set()
    for line in r.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) < 3 or fields[0] != "SUMMARY" or fields[2] != "suspends":
            continue
        # The module is the longest leading run of the identity naming one.
        parts = written_name(fields[1]).split(".")
        for cut in range(len(parts) - 1, 0, -1):
            candidate = ".".join(parts[:cut])
            if candidate in modules:
                holding.add(candidate)
                break
    return holding, None


def check_new_std(sawc2):
    """Failures of the new std's cross-check: the modules spelling a park
    point, closed over their importers, against the modules sawc2 finds a
    suspending function in."""
    holding, problem = new_std_suspending_modules(sawc2)
    if holding is None:
        return ["std suspension: the new std's cross-check cannot run: %s" % problem]
    parks = parking_modules(NEW_STD, NEW_PARK_SPELLINGS, new_module_of)
    failures = []
    for module in sorted(holding - parks):
        failures.append("std suspension: sawc2 finds a suspending function in %s, but no body of "
                        "it calls a park point or imports a module that does" % module)
    for module in sorted(parks - holding):
        failures.append("std suspension: %s calls a park point, or imports a module that does, "
                        "but sawc2 finds no suspending function in it" % module)
    return failures


def check():
    """(failures, counts): the Saw form against the recorded table, and the
    new std's cross-check. The table is Stage 0's verdicts on its frozen std,
    so it is observed and its rows checked against that std's sources only
    when `--write` records it."""
    rows, triple = read_table()
    failures = []
    if not rows or triple is None:
        failures.append("std suspension: %s holds no rows or no `%s` line; rerun "
                        "compiler/tools/std_suspension.py --write" % (os.path.relpath(TABLE_FILE, REPO),
                                                                       _TRIPLE.strip()))
    failures += check_new_std(build.SAWC2)
    try:
        with open(SAW_FILE) as fh:
            current = fh.read()
    except OSError:
        current = None
    if current != saw_text(rows):
        failures.append("std suspension: %s differs from %s; rerun compiler/tools/std_suspension.py "
                        "--write and review the difference" % (os.path.relpath(SAW_FILE, REPO),
                                                               os.path.relpath(TABLE_FILE, REPO)))
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
        failures = check_rows(rows)
        for failure in failures:
            print(failure)
        if failures:
            print("std suspension: nothing written")
            return 1
        with open(TABLE_FILE, "w") as fh:
            fh.write(table_text(rows, build.host_triple()))
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
