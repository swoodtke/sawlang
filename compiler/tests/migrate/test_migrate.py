"""The corpus rewriter's golden fixtures, and the pairing check (SL-418).

Each fixture in fixtures/ is NAME.before, NAME.after (the migration; absent
when the file must come out unchanged), NAME.sites (the file's statuses, then
one `LINE RULE STATUS` line per site, followed by ` => AFTER` for an applied
site and ` -- REASON` for any other) and, for the manual pass, NAME.manual
(manual.tsv's rows without the path column); a NAME.hold file stands for a
`flagged` decisions.tsv row. A before text is a program the
frozen compiler checks, except where the fixture is about what happens when
it does not (a removed form, a blind spot). A `// expected: REASON` line
stands in for the file's corpus_expected.tsv row. The instrument runs on each
fixture, and the pipeline's output must match the goldens exactly;
`test_migrate.py --write` rewrites them for review.
"""
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TOOL = os.path.join(REPO, "compiler", "tools", "migrate")
FIXTURES = os.path.join(HERE, "fixtures")
OUT = os.path.join(REPO, ".build", "migrate-tests")
if TOOL not in sys.path:
    sys.path.insert(0, TOOL)

import layout  # noqa: E402
import manifest  # noqa: E402
import migrate  # noqa: E402
import pipeline  # noqa: E402
import rules  # noqa: E402
import scan  # noqa: E402

INSTRUMENT = os.path.join(TOOL, "instrument.py")


def names():
    return sorted(f[:-len(".before")] for f in os.listdir(FIXTURES) if f.endswith(".before"))


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def observe(name):
    """The instrument's records for one fixture, compiled as a lone entry."""
    os.makedirs(OUT, exist_ok=True)
    src = os.path.join(OUT, name + ".saw")
    shutil.copyfile(os.path.join(FIXTURES, name + ".before"), src)
    out = os.path.join(OUT, name + ".json")
    r = subprocess.run([sys.executable, INSTRUMENT, out, "--", src, "-o", os.path.join(OUT, name)],
                       cwd=REPO, capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED="0"))
    if not os.path.exists(out):
        return None, "the instrument wrote nothing: %s" % r.stderr[-400:]
    with open(out, encoding="utf-8") as fh:
        return json.load(fh), None


def job_for(name, records, accessors):
    text = read(os.path.join(FIXTURES, name + ".before"))
    rel = os.path.relpath(os.path.join(OUT, name + ".saw"), REPO)
    expected = None
    for line in layout.header(text):
        if "// expected:" in line:
            expected = ("FAIL", line.split("// expected:", 1)[1].strip())
    mine = [r for r in records if r.get("file") == rel]
    walked = sorted({(r["line"], r["col"]) for r in mine if r["kind"] == "walked"})
    path = "examples/%s.saw" % name
    passes = {"mechanical", "grammar"}
    manual = None
    manual_path = os.path.join(FIXTURES, name + ".manual")
    if os.path.exists(manual_path):
        passes.add("manual")
        rows, problems = manifest.load(manual_path, migrate.MANUAL_HEADER[1:])
        if problems:
            raise ValueError("; ".join(problems))
        manual = migrate.group_manual([dict(r, path=path) for r in rows], lambda p: p)[path]
    return {"path": path, "text": text, "passes": passes,
            "windows": [r for r in mine if r["kind"] == "window"],
            "closures": [r for r in mine if r["kind"] == "closure"],
            "walked": walked, "accessors": accessors, "expected": expected, "manual": manual,
            "hold": os.path.exists(os.path.join(FIXTURES, name + ".hold"))}


def site_lines(res):
    lines = ["status: " + ",".join(res.statuses)]
    for row in sorted(res.sites, key=lambda r: (r["line"], r["col"], r["rule"])):
        line = "%s %s %s" % (row["line"], row["rule"], row["status"])
        if row["status"] in ("rewritten", "manual"):
            line += " => " + manifest.cell(row["after"])
        else:
            line += " -- " + manifest.cell(row["reason"])
        lines.append(line)
    return lines


def reason_class(rule, reason):
    """A flag's rule and reason with the site's particulars (the names in
    backticks, an AST position) taken out, so one fixture covers a class."""
    text = re.sub(r"`[^`]*`", "`…`", reason)
    return rule, re.sub(r"\([A-Za-z]+\.[a-z_]+(\[\d+\])?\)", "(…)", text)


def uncovered_reasons(covered, root=REPO):
    """A failure line per class of flag in the corpus manifest that no
    fixture refuses."""
    path = os.path.join(root, layout.TARGET, manifest.SITES)
    if not os.path.exists(path):
        return []
    rows, _ = manifest.load(path, manifest.SITE_HEADER)
    used = sorted({reason_class(r["rule"], r["reason"]) for r in rows if r["status"] == "flagged"})
    return ["migrate fixtures: no fixture refuses %s: %s" % key for key in used if key not in covered]


def unrecorded_manual_rows(root=REPO):
    """A failure line per manual.tsv row, companion rows included, with no
    row of its own in the corpus's sites manifest."""
    path = os.path.join(root, layout.TARGET, manifest.SITES)
    if not os.path.exists(path) or not os.path.exists(migrate.MANUAL):
        return []
    sites, _ = manifest.load(path, manifest.SITE_HEADER)
    recorded = {(s["path"], s["line"], s["col"]) for s in sites
                if s["status"] in ("manual", "reviewed", "withheld")}
    fails = []
    for rows in migrate.load_manual().values():
        for m in rows:
            if (m["path"], str(m["line"]), str(m["col"])) not in recorded:
                fails.append("migrate: manual.tsv row %s:%d:%d has no site row in %s"
                             % (m["path"], m["line"], m["col"], manifest.SITES))
    return fails


def check_fixture(name, observed, accessors, write=False, covered=None):
    failures = []
    records, why = observed
    if records is None:
        return ["migrate fixture %s: %s" % (name, why)]
    res = pipeline.process(job_for(name, records, accessors))
    if covered is not None:
        covered.update(reason_class(r["rule"], r["reason"]) for r in res.sites
                       if r["status"] == "flagged")
    before = read(os.path.join(FIXTURES, name + ".before"))
    after_path = os.path.join(FIXTURES, name + ".after")
    sites_path = os.path.join(FIXTURES, name + ".sites")
    got_sites = site_lines(res)
    if write:
        if res.text != before:
            with open(after_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(res.text)
        elif os.path.exists(after_path):
            os.remove(after_path)
        with open(sites_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(got_sites) + "\n")
        return []
    want = read(after_path) if os.path.exists(after_path) else before
    if res.text != want:
        failures.append("migrate fixture %s: the migrated text differs from %s"
                        % (name, os.path.basename(after_path) if os.path.exists(after_path)
                           else "the before text"))
    want_sites = [ln for ln in read(sites_path).split("\n") if ln] if os.path.exists(sites_path) else []
    if got_sites != want_sites:
        failures.append("migrate fixture %s: sites differ: want %s, got %s"
                        % (name, want_sites, got_sites))
    return failures


PAIRING_CASES = {
    # name: (examples files, copies, manifest rows, site rows, a substring each failure list must hold)
    "clean": ({"a.saw": "x\n"}, {"a.saw": "x\n"}, [("a.saw", "copied", "", "")], [], None),
    "no twin": ({"a.saw": "x\n"}, {}, [("a.saw", "copied", "", "")], [], "has no twin"),
    "frozen-only": ({"a.saw": "x\n"}, {}, [("a.saw", "frozen-only", "", "a sawos pin")], [], None),
    "frozen-only without a reason": ({"a.saw": "x\n"}, {}, [("a.saw", "frozen-only", "", "")], [],
                                     "names its reason"),
    "retired": ({"a.saw": "x\n"}, {}, [("a.saw", "retired", "", "retired: the form is gone")], [], None),
    "retired without a reason": ({"a.saw": "x\n"}, {}, [("a.saw", "retired", "", "")], [],
                                 "a retired row names its reason"),
    "retired with a twin": ({"a.saw": "x\n"}, {"a.saw": "x\n"},
                            [("a.saw", "retired", "", "retired: the form is gone")], [],
                            "is retired but has a twin"),
    "stray copy": ({}, {"b.saw": "x\n"}, [("b.saw", "copied", "", "")], [], "has no original"),
    "new copy": ({}, {"b.saw": "x\n"}, [("b.saw", "new", "", "")], [], None),
    "no row": ({"a.saw": "x\n"}, {"a.saw": "x\n"}, [], [], "has no manifest row"),
    "xfail parity": ({"a.saw": "// XFAIL: DF-1a pin\n"}, {"a.saw": "x\n"},
                     [("a.saw", "copied", "", "")], [], "XFAIL markers differ"),
    "rule count": ({"a.saw": "x\n"}, {"a.saw": "y\n"}, [("a.saw", "rewritten", "A1.field-write:2", "")],
                   [("a.saw", "1", "1", "A1.field-write", "rewritten")], "counts 2"),
    "copied differs": ({"a.saw": "x\n"}, {"a.saw": "y\n"}, [("a.saw", "copied", "", "")], [],
                       "differs from its original"),
    "flagged differs": ({"a.saw": "x\n"}, {"a.saw": "y\n"}, [("a.saw", "flagged", "", "C: why")], [],
                        "differs from its original"),
    "rewritten unchanged": ({"a.saw": "x\n"}, {"a.saw": "x\n"},
                            [("a.saw", "rewritten", "A1.field-write:1", "")],
                            [("a.saw", "1", "1", "A1.field-write", "rewritten")], "marked changed"),
    "reviewed": ({"a.saw": "x\n"}, {"a.saw": "x\n"}, [("a.saw", "reviewed", "reviewed.C:1", "")],
                 [("a.saw", "1", "1", "C", "reviewed", "", "", "", "left as it is")], None),
    "withheld without a reason": ({"a.saw": "x\n"}, {"a.saw": "x\n"}, [("a.saw", "flagged", "", "C: why")],
                                  [("a.saw", "1", "1", "A1.field-write", "withheld")],
                                  "a withheld site names its reason"),
    "uncommitted delete": ({"a.saw": None}, {"a.saw": "x\n"}, [("a.saw", "copied", "", "")], [],
                           "missing from the working tree"),
    "xfail-if parity": ({"a.saw": "// XFAIL-IF: macos DF-1a pin\n"}, {"a.saw": "x\n"},
                        [("a.saw", "rewritten", "", "")], [], "XFAIL markers differ"),
    "xfail unspaced parity": ({"a.saw": "//XFAIL: DF-1a pin\n"}, {"a.saw": "x\n"},
                              [("a.saw", "rewritten", "", "")], [], "XFAIL markers differ"),
}


def check_pairing_cases():
    """The pairing check refuses each way the trees and manifests can disagree."""
    failures = []
    for name, (sources, copies, rows, sites, want) in sorted(PAIRING_CASES.items()):
        root = os.path.join(OUT, "pairing", name.replace(" ", "-"))
        shutil.rmtree(root, ignore_errors=True)
        files = {}
        for tree, content in ((layout.SOURCE, sources), (layout.TARGET, copies)):
            for rel_path, text in content.items():
                files.setdefault(tree, []).append(tree + "/" + rel_path)
                if text is None:
                    # Tracked, but deleted from the working tree.
                    continue
                path = os.path.join(root, tree, rel_path)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
        os.makedirs(os.path.join(root, layout.TARGET), exist_ok=True)
        manifest.write(root, [dict(zip(manifest.FILE_HEADER, r)) for r in rows],
                       [dict(zip(manifest.SITE_HEADER, s + ("",) * (9 - len(s)))) for s in sites])
        got = manifest.pairing_failures(root, lambda prefix, _root: sorted(files.get(prefix, [])))
        if want is None and got:
            failures.append("pairing case %r: unexpected %s" % (name, got))
        elif want is not None and not any(want in g for g in got):
            failures.append("pairing case %r: no failure says %r (got %s)" % (name, want, got))
    return failures


def refusal(want, action):
    """A failure line unless `action()` refuses with a message holding `want`."""
    try:
        action()
    except (ValueError, SystemExit) as e:
        return [] if want in str(e) else ["refusal %r: got %r" % (want, str(e))]
    return ["refusal %r: nothing was refused" % want]


def manual_job(text, rows):
    """A manual-only job for one `examples/` file, from manual.tsv-shaped rows
    (line, col, rule, old, new) without the path or rationale."""
    path = "examples/case.saw"
    full = [dict(zip(migrate.MANUAL_HEADER, (path, str(r[0]), str(r[1]), r[2], r[3], r[4], "why")))
            for r in rows]
    return {"path": path, "text": text, "passes": {"manual"},
            "manual": migrate.group_manual(full, lambda p: p)[path]}


MANUAL_TEXT = "// one\n// two\n// EXPECT: success\n\nfunc main() {}\n"
MANUAL_REFUSALS = {
    # message: manual rows (line, col, rule, old, new)
    "an anchor row sits at line 0": [(1, 0, pipeline.ANCHOR, "", "")],
    "and edits nothing": [(0, 0, pipeline.ANCHOR, "x", "y")],
    "a drop row's old text is its whole line": [(0, 0, pipeline.ANCHOR, "", ""),
                                                 (1, 0, pipeline.DROP, "one", "")],
    "and its new text is empty": [(0, 0, pipeline.ANCHOR, "", ""),
                                  (1, 0, pipeline.DROP, "// one", "// uno")],
    "a companion row follows no row of its file": [(1, 0, pipeline.COMPANION, "// one", "// uno")],
}


def check_manual_refusals():
    """The manual pass refuses a misplaced anchor, a drop row that is not a
    whole line, and a companion with no row before it."""
    failures = []
    for want, rows in sorted(MANUAL_REFUSALS.items()):
        failures += refusal(want, lambda rows=rows: pipeline.process(manual_job(MANUAL_TEXT, rows)))
    return failures


def check_decisions():
    """decisions.tsv: a file that comes out with another primary status than
    its decision fails `apply`, and a malformed table is refused whole."""
    failures = []
    row = {"path": "a.saw", "status": "reviewed,expectation-pending", "rules": "", "notes": "old"}
    failures += refusal("a.saw is decided manual but came out reviewed,expectation-pending",
                        lambda: migrate.decided_row(dict(row), "manual", "re-aimed"))
    got = migrate.decided_row(dict(row), "reviewed", "left as it is")["notes"]
    if got != "left as it is; old":
        failures.append("decided_row: want the decision's note before the row's, got %r" % got)
    os.makedirs(OUT, exist_ok=True)
    table = os.path.join(OUT, "decisions.tsv")
    for want, lines in (("unknown decision 'kept'", ["a.saw\tkept\twhy"]),
                        ("a.saw: a decision names its reason", ["a.saw\tretired\t-"]),
                        ("a.saw has two decisions", ["a.saw\tretired\twhy", "a.saw\treviewed\twhy"])):
        with open(table, "w", encoding="utf-8") as fh:
            fh.write("\n".join(["\t".join(migrate.DECISIONS_HEADER)] + lines) + "\n")
        failures += refusal(want, lambda: migrate.load_decisions(table))
    copied = {"path": "a.saw", "status": "copied,expectation-pending", "rules": "", "notes": "-"}
    got = migrate.decided_row(dict(copied), "reviewed", "read whole")["status"]
    if got != "reviewed,expectation-pending":
        failures.append("decided_row: a reviewed decision on a copied file makes it reviewed, "
                        "got %r" % got)
    failures += refusal("a.saw is decided rewritten but came out copied",
                        lambda: migrate.decided_row(dict(copied, status="copied"), "rewritten", "x"))
    return failures


SUBSCRIPT_TEXTS = {
    # name: (text, struct, whether it declares a shared `[]` for the struct)
    "explicit shared": ("extension Bag {\n    func [](&self, i: Int) borrows -> &Int { lend self.c }\n}\n",
                        "Bag", True),
    "synthesized": ("extension Bag {\n    @synthesize(shared)\n    public func [](&var self, i: Int) "
                    "borrows -> &var Int { lend self.c }\n}\n", "Bag", True),
    "generic": ("extension Holder<T> {\n    func [](&self, i: Int) borrows -> &T { lend self.c }\n}\n",
                "Holder", True),
    "exclusive only": ("extension Bag {\n    func [](&var self, i: Int) borrows -> &var Int "
                       "{ lend self.c }\n}\n", "Bag", False),
    "another type's twin": ("extension Row {\n    func [](&self, i: Int) borrows -> &Int { lend self.c }\n}\n"
                            "extension Bag {\n    func [](&var self, i: Int) borrows -> &var Int "
                            "{ lend self.c }\n}\n", "Bag", False),
    "a named accessor": ("extension Bag {\n    func at(&self, i: Int) borrows -> &Int { lend self.c }\n}\n",
                         "Bag", False),
}


def check_getitem_decisions():
    """A getitem row's decision must agree with the migrated text: (a) needs a
    shared `[]` for the struct, (b) none, and a (b) row that leaves the plain
    subscript in place needs an error test."""
    failures = []
    for name, (text, struct, want) in sorted(SUBSCRIPT_TEXTS.items()):
        if rules.declares_shared_subscript(text, struct) != want:
            failures.append("declares_shared_subscript %r: want %s" % (name, want))
    shared, exclusive = SUBSCRIPT_TEXTS["synthesized"][0], SUBSCRIPT_TEXTS["exclusive only"][0]
    for want, args in (("opens with its decision", ("Bag", "kept", True, shared, "success")),
                       ("decided (a), but", ("Bag", "(a) twin", True, exclusive, "success")),
                       ("decided (b), but", ("Bag", "(b) none", False, shared, "success")),
                       ("in a file that does not expect an error",
                        ("Bag", "(b) none", True, exclusive, "success"))):
        got = rules.getitem_decision_problem(*args)
        if got is None or want not in got:
            failures.append("getitem_decision_problem: want %r, got %r" % (want, got))
    for args in (("Bag", "(a) twin", True, shared, "success"),
                 ("Bag", "(b) none", True, exclusive, "error"),
                 ("Bag", "(b) none", False, exclusive, "success")):
        got = rules.getitem_decision_problem(*args)
        if got is not None:
            failures.append("getitem_decision_problem %r: unexpected %r" % (args[1:3], got))
    row = pipeline.site_row("examples/case.saw", 3, 6, rules.GETITEM, "reviewed",
                            evidence="Bag.[] elem=Int", reason="(a) twin")
    failures += refusal("examples/case.saw:3:6: decided (a)",
                        lambda: pipeline.check_getitem_rows("examples/case.saw", [row], exclusive))
    return failures


def run(write=False):
    failures, counts = [], {}
    accessors = sorted(scan.accessor_names())
    fixtures = names()
    # The instrument runs one process per fixture; the pipeline runs here, in
    # order, since the recognizer it checks with is built once per process.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        observed = list(pool.map(observe, fixtures))
    covered = set()
    for name, obs in zip(fixtures, observed):
        failures.extend(check_fixture(name, obs, accessors, write, covered))
    counts["migrate fixtures"] = len(fixtures)
    if write:
        return failures, counts
    failures.extend(uncovered_reasons(covered))
    counts["flag classes covered"] = len(covered)
    failures.extend(unrecorded_manual_rows())
    failures.extend(check_pairing_cases())
    counts["pairing check cases"] = len(PAIRING_CASES)
    failures.extend(check_manual_refusals())
    counts["manual refusal cases"] = len(MANUAL_REFUSALS)
    failures.extend(check_decisions())
    counts["decisions checks"] = 1
    failures.extend(check_getitem_decisions())
    counts["getitem decision cases"] = len(SUBSCRIPT_TEXTS)
    failures.extend(manifest.pairing_failures())
    counts["corpus pairing checks"] = 1
    return failures, counts


def main():
    failures, counts = run(write="--write" in sys.argv[1:])
    for f in failures:
        print(f)
    print("migrate tests: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                     ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
