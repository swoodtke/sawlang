#!/usr/bin/env python3
"""Which codegen units an edit to one Saw module changes (SL-955).

    tools/unit_stability.py [--case NAME]... [--g0] [--explain N] [--sawc PATH] [--json FILE] [--list]

Each case builds two copies of a program's sources under `.build/unit_stability/`
with `sawc build --codegen-units=module -O0`, the second with its edit (the
tracked tree is never touched), and pairs their units by shared defined
symbols. A changed unit is classed by the smallest normalization that makes
the texts equal: `bytes` (`.bytes.N`), `metadata` (also `!N`), `attributes`
(also `#N`), `order` (also line order), else `content`. The `control` case
edits nothing, so a unit it reports changed depends on the build's directory.
"""
import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))

import build  # noqa: E402

WORK = os.path.join(build.BUILD_DIR, "unit_stability")
BUILD_TIMEOUT_S = 1800

# A program: its entry, its `--module-path` packages (name, directory), and
# the source directories a copy of it holds, all relative to the repository.
Program = collections.namedtuple("Program", "entry packages sources")
SAWC_PACKAGES = tuple(build.STAGE_PACKAGES)
PROGRAMS = {
    "sawc": Program("compiler/driver/src/main.saw", SAWC_PACKAGES,
                    ("std", "compiler/driver/src") + tuple(rel for _, rel in SAWC_PACKAGES)),
    "blade": Program("blade/src/main.saw",
                     (("blade", "blade/src"), ("toml", "libs/toml/src"), ("semver", "libs/semver/src"),
                      ("imgformat", "libs/imgformat/src")),
                     ("std", "blade/src", "libs/toml/src", "libs/semver/src", "libs/imgformat/src")),
}

# A case: its program, the file it edits, the text replaced (exactly once in
# the file) and its replacement, and the name of the module edited.
Case = collections.namedtuple("Case", "program path old new module about")
CASES = collections.OrderedDict([
    ("control", Case("sawc", None, None, None, None, "sawc, no edit: two copies of the same tree")),
    ("sawc-body", Case("sawc", "compiler/resolve/src/dump.saw",
                       "        try! order.push(k)\n        k = k + 1\n",
                       "        try! order.push(k)\n        k = k + 2 - 1\n",
                       "sawresolve.dump", "sawc, a function body in one stage (res_sort_strings)")),
    ("sawc-std-function", Case("sawc", "std/path.saw",
                               "        if other.byte_at(0) == 47 {  // '/'\n",
                               "        if path_slash_at(&other, 0) {\n",
                               "std.path", "sawc, a new function in one std module (std.path, called by join)")),
    ("sawc-string", Case("sawc", "compiler/eval/src/report.saw",
                         "        try! msg.append(\"the evaluation runs past its step budget, through \")\n",
                         "        try! msg.append(\"the evaluation runs past its step budget, through \")\n"
                         "        try! msg.append(\"unit stability probe: \")\n",
                         "saweval.report", "sawc, a new string literal in one module (saweval.report)")),
    ("sawc-new-call", Case("sawc", "compiler/driver/src/main.saw",
                           "    let command = args.get(1) ?? \"\"\n",
                           "    let command = args.get(1) ?? \"\"\n"
                           "    if command.equals(\"unit-stability-probe\") {\n"
                           "        let plan = LlUnitPlan()\n"
                           "        var problems = Vector<String>()\n"
                           "        let units = ll_split(&command, &plan, &var problems)\n"
                           "        return units.len()\n"
                           "    }\n",
                           "main", "sawc, a new call from the driver's main to another module (ll_split)")),
    ("blade-body", Case("blade", "blade/src/git.saw",
                        "        i = i + 1\n    }\n    true\n}\n",
                        "        i = i + 2 - 1\n    }\n    true\n}\n",
                        "blade.git", "Blade, a function body (looks_like_version)")),
    ("blade-string", Case("blade", "blade/src/git.saw",
                          "    if v.starts_with(\"v\") {\n",
                          "    if v.starts_with(\"v\") || v.starts_with(\"unit stability probe\") {\n",
                          "blade.git", "Blade, a new string literal (tag_version)")),
    ("blade-closure", Case("blade", "blade/src/git.saw",
                           "    if looks_like_version(v) {\n",
                           "    let check = { s: String in looks_like_version(s) }; if check(v) {\n",
                           "blade.git", "Blade, a new closure signature, `(String) -> Bool` (tag_version)")),
    ("blade-tuple", Case("blade", "blade/src/git.saw",
                         "    if looks_like_version(v) {\n",
                         "    let pair = (v, [v]); if looks_like_version(pair.0) {\n",
                         "blade.git", "Blade, a new tuple and array type, `(String, [String; 1])` (tag_version)")),
])
# The function `sawc-std-function` adds, at the end of std/path.saw.
STD_FUNCTION = """
// Whether `text` has a `/` at `at` (SL-955's unit stability measure).
func path_slash_at(text: &String, at: Int) -> Bool {
    text.byte_at(at) == 47
}
"""

# A unit's own definitions; a `private` or `linkonce_odr` copy, which several
# units hold under one name, pairs nothing.
DEFINE = re.compile(r'^define (?!private |linkonce_odr )[^@]*(@(?:"[^"]*"|[-\w.$]+))')
GLOBAL = re.compile(r'^(@(?:"[^"]*"|[-\w.$]+)) = (?!external |private )')
SUBPROGRAM_FILE = re.compile(r"^!\d+ = distinct !DISubprogram\(.*?, file: !(\d+),")
DIFILE = re.compile(r'^!(\d+) = !DIFile\(filename: "([^"]*)"')
NORMALIZE = (("bytes", re.compile(r"@\.bytes\.\d+"), "@.bytes.N"),
             ("metadata", re.compile(r"!\d+"), "!N"),
             ("attributes", re.compile(r"#\d+"), "#N"))


def copy_program(program, root):
    """A fresh copy of `program`'s sources under `root`."""
    shutil.rmtree(root, ignore_errors=True)
    for rel in program.sources:
        shutil.copytree(os.path.join(REPO, rel), os.path.join(root, rel))


def apply_edit(case, root):
    path = os.path.join(root, case.path)
    with open(path) as fh:
        text = fh.read()
    if text.count(case.old) != 1:
        raise RuntimeError("%s: the edit's text occurs %d times in %s, not once"
                           % (case.about, text.count(case.old), case.path))
    text = text.replace(case.old, case.new)
    if case.path == "std/path.saw":
        text += STD_FUNCTION
    with open(path, "w") as fh:
        fh.write(text)


def build_units(sawc, program, root, flags):
    """{unit file name: text} of the split build of the copy at `root`, with
    the extra `flags`."""
    out = os.path.join(root, "out", "program")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    # The units' text is what is measured; no object from the user's cache is wanted.
    argv = [sawc, "build", "-O0", "--codegen-units=module", "--no-object-cache", "--std-root", "std"] + list(flags)
    for name, rel in program.packages:
        argv += ["--module-path", "%s=%s" % (name, rel)]
    argv += [program.entry, "-o", out]
    r = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError("the build in %s exits %d: %s" % (root, r.returncode, (r.stdout + r.stderr)[-1500:]))
    units = {}
    directory = out + ".units"
    for name in sorted(os.listdir(directory)):
        if name.endswith(".ll"):
            with open(os.path.join(directory, name)) as fh:
                units[name] = fh.read()
    return units


def defined_symbols(text):
    found = set()
    for line in text.split("\n"):
        m = DEFINE.match(line) or GLOBAL.match(line)
        if m:
            found.add(m.group(1))
    return found


def unit_label(text, symbols):
    """The source file most of the unit's subprograms are in, `+N` for the
    other files it has subprograms in; `-program` for the unit with `main`."""
    if "@main" in symbols:
        return "-program"
    files = {}
    counts = collections.Counter()
    for line in text.split("\n"):
        m = DIFILE.match(line)
        if m:
            files[m.group(1)] = m.group(2)
            continue
        m = SUBPROGRAM_FILE.match(line)
        if m and "DIFlagArtificial" not in line:
            counts[m.group(1)] += 1
    named = [files.get(f, "?") for f, _ in counts.most_common()]
    if not named:
        return "?"
    return named[0] + (" +%d" % (len(named) - 1) if len(named) > 1 else "")


def module_symbols(symbols, module):
    """How many of `symbols` are items written in module `module` (its
    functions and their resume functions)."""
    marks = ('@"saw %s.' % module, '@"saw resume %s.' % module)
    return sum(1 for s in symbols if s.startswith(marks))


def normalized(text):
    for _, pattern, spelled in NORMALIZE:
        text = pattern.sub(spelled, text)
    return text


def differing_lines(a, b, limit):
    """Up to `limit` lines of each side, normalized, that the other lacks."""
    la = collections.Counter(normalized(a).split("\n"))
    lb = collections.Counter(normalized(b).split("\n"))
    gone = [line for line in (la - lb).elements()][:limit]
    new = [line for line in (lb - la).elements()][:limit]
    return gone, new


def classify(a, b):
    """The smallest normalization under which texts `a` and `b` are equal."""
    if a == b:
        return "same"
    for name, pattern, spelled in NORMALIZE:
        a = pattern.sub(spelled, a)
        b = pattern.sub(spelled, b)
        if a == b:
            return name
    if sorted(a.split("\n")) == sorted(b.split("\n")):
        return "order"
    return "content"


def pair_units(base, edit):
    """[(base file or None, edit file or None)]: each edit unit with the base
    unit sharing the most defined symbols, then the base units left over."""
    owner = {}
    for name, (_, symbols) in base.items():
        for s in symbols:
            owner[s] = name
    pairs = []
    taken = set()
    for name, (_, symbols) in sorted(edit.items()):
        votes = collections.Counter(owner[s] for s in symbols if s in owner)
        match = next((b for b, _ in votes.most_common() if b not in taken), None)
        if match is not None:
            taken.add(match)
        pairs.append((match, name))
    for name in sorted(base):
        if name not in taken:
            pairs.append((name, None))
    return pairs


def measure(sawc, name, case, explain=0, flags=()):
    program = PROGRAMS[case.program]
    root = os.path.join(WORK, name)
    base_root = os.path.join(root, "base")
    edit_root = os.path.join(root, "edit")
    copy_program(program, base_root)
    copy_program(program, edit_root)
    if case.path:
        apply_edit(case, edit_root)
    rows = compare_units(build_units(sawc, program, base_root, flags), build_units(sawc, program, edit_root, flags),
                         case.module, explain)
    return {"case": name, "about": case.about, "units": sum(1 for r in rows if r["edit"]), "rows": rows}


def compare_units(base_texts, edit_texts, module=None, explain=0):
    """A row per unit of two builds ({file: text} each), paired by shared
    defined symbols: its files, label, class, and whether it is the unit of
    the edited module `module` (the one defining most of its items).
    compiler/tests/run/run_lane.py's stability pin shares it."""
    base = {k: (t, defined_symbols(t)) for k, t in base_texts.items()}
    edit = {k: (t, defined_symbols(t)) for k, t in edit_texts.items()}
    rows = []
    for b, e in pair_units(base, edit):
        text_b = base[b][0] if b else ""
        text_e = edit[e][0] if e else ""
        label = unit_label(text_e or text_b, edit[e][1] if e else base[b][1])
        kind = classify(text_b, text_e) if b and e else ("added" if e else "removed")
        row = {"base": b, "edit": e, "label": label, "kind": kind, "edited": False,
               "weight": module_symbols(edit[e][1] if e else base[b][1], module) if module else 0}
        if kind == "content":
            row["gone"], row["new"] = differing_lines(text_b, text_e, explain)
        rows.append(row)
    heaviest = max(rows, key=lambda r: r["weight"]) if rows else None
    if heaviest is not None and heaviest["weight"] > 0:
        heaviest["edited"] = True
    return rows


def report(result):
    changed = [r for r in result["rows"] if r["kind"] != "same"]
    lines = ["%s: %s: %d units, %d changed" % (result["case"], result["about"], result["units"], len(changed))]
    for r in changed:
        lines.append("    %-9s %s%s" % (r["kind"], r["label"], "  (the edited module's unit)" if r["edited"] else ""))
        for line in r.get("gone", []):
            lines.append("        - %s" % line[:200])
        for line in r.get("new", []):
            lines.append("        + %s" % line[:200])
    return "\n".join(lines)


def table(results):
    """The Markdown table for a tracker comment: units changed per edit, and
    how many besides the edited module's own and the program unit."""
    lines = ["| edit | units | changed | other than the edited module's and -program | kinds |",
             "|---|---:|---:|---:|---|"]
    for result in results:
        changed = [r for r in result["rows"] if r["kind"] != "same"]
        other = [r for r in changed if not r["edited"] and r["label"] != "-program"]
        kinds = collections.Counter(r["kind"] for r in changed)
        lines.append("| %s | %d | %d | %d | %s |" % (result["about"], result["units"], len(changed), len(other),
                                                   ", ".join("%s %d" % kv for kv in sorted(kinds.items())) or "-"))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", action="append", choices=list(CASES))
    ap.add_argument("--sawc", default=build.SAWC)
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--explain", type=int, default=0, metavar="N",
                    help="print up to N differing lines of each side of a unit whose content changed")
    ap.add_argument("--g0", action="store_true", help="build without line tables")
    args = ap.parse_args()
    if args.list:
        for name, case in CASES.items():
            print("%-18s %s" % (name, case.about))
        return 0
    sawc = os.path.abspath(args.sawc)
    results = []
    for name in args.case or list(CASES):
        print("unit stability: %s" % name, file=sys.stderr, flush=True)
        result = measure(sawc, name, CASES[name], args.explain, ["-g0"] if args.g0 else [])
        print(report(result), flush=True)
        results.append(result)
    print()
    print(table(results))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
