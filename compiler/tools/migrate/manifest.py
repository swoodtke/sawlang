"""The migration's two manifests and the pairing check that reads them.

MIGRATION.tsv has one row per file, keyed by its path below the corpus root,
which is the same under examples/ and tests/corpus/. MIGRATION_SITES.tsv has
one row per rewritten, flagged, withheld, hand-migrated or reviewed site. A
reviewed site or file is one a person looked at and left unchanged; manual
means changed by hand. A retired file tests nothing the language still has:
it stays in examples/, has no twin, and its note names what retired it.

ENTRY POINTS
    write
    load
    pairing_failures
"""
import os
import re

import layout

MANIFEST = "MIGRATION.tsv"
SITES = "MIGRATION_SITES.tsv"
FILE_HEADER = ("path", "status", "rules", "notes")
SITE_HEADER = ("path", "line", "col", "rule", "status", "before", "after", "evidence", "reason")
STATUSES = {"copied", "rewritten", "manual", "reviewed", "flagged", "expectation-pending",
            "ir-test", "grammar-flip", "frozen-only", "retired", "new"}
PRIMARY = {"copied", "rewritten", "manual", "reviewed", "flagged", "frozen-only", "retired", "new"}
# A file with one of these statuses has no twin, and its row names why.
TWINLESS = ("frozen-only", "retired")
# A twin with one of these statuses is its original, byte for byte.
UNCHANGED = {"copied", "reviewed", "flagged"}
SITE_STATUSES = {"rewritten", "flagged", "withheld", "manual", "reviewed"}
# Every XFAIL spelling test_runner.py or check_citations.py reads.
XFAIL = re.compile(r"//\s*XFAIL(-IF)?:")


EMPTY = "-"


def cell(value):
    """A value as one cell. An empty cell is written `-`, since a line that
    ends in a tab is trailing whitespace to git and to the patch server."""
    text = str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")
    return text if text else EMPTY


def rel(path):
    """A path below the corpus root, from either tree's repository path."""
    for root in (layout.SOURCE, layout.TARGET):
        if path.startswith(root + "/"):
            return path[len(root) + 1:]
    raise ValueError(path)


def write(root, file_rows, site_rows):
    target = os.path.join(root, layout.TARGET)
    with open(os.path.join(target, MANIFEST), "w", encoding="utf-8") as fh:
        fh.write("\t".join(FILE_HEADER) + "\n")
        for row in sorted(file_rows, key=lambda r: r["path"]):
            fh.write("\t".join(cell(row[k]) for k in FILE_HEADER) + "\n")
    with open(os.path.join(target, SITES), "w", encoding="utf-8") as fh:
        fh.write("\t".join(SITE_HEADER) + "\n")
        for row in sorted(site_rows, key=lambda r: (r["path"], r["line"], r["col"], r["rule"])):
            fh.write("\t".join(cell(row[k]) for k in SITE_HEADER) + "\n")


def load(path, header):
    """([row dict], [problem]) for one manifest."""
    rows, problems = [], []
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if not lines or lines[0] != "\t".join(header):
        problems.append("%s: the first line must be the header %s" % (path, "\t".join(header)))
        return rows, problems
    for n, line in enumerate(lines[1:], 2):
        if not line:
            continue
        cells = ["" if c == EMPTY else c for c in line.split("\t")]
        if len(cells) != len(header):
            problems.append("%s:%d: want %d tab-separated cells" % (path, n, len(header)))
            continue
        rows.append(dict(zip(header, cells)))
    return rows, problems


def xfail_lines(text):
    """Every line carrying an XFAIL marker, stripped."""
    return [line.strip() for line in text.split("\n") if XFAIL.search(line)]


def read_bytes(root, path, fails):
    """A tracked file's bytes, or None with a failure line when the working
    tree no longer has it (an uncommitted delete)."""
    try:
        with open(os.path.join(root, path), "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        fails.append("pairing: %s is tracked but missing from the working tree" % path)
        return None


def pairing_failures(root=layout.REPO, tracked=layout.tracked):
    """Every way the two trees and the manifests disagree, as failure lines.
    `tracked(prefix, root)` lists a tree's files."""
    fails = []
    target = os.path.join(root, layout.TARGET)
    manifest_path = os.path.join(target, MANIFEST)
    sites_path = os.path.join(target, SITES)
    for p in (manifest_path, sites_path):
        if not os.path.exists(p):
            return ["pairing: %s is missing" % os.path.relpath(p, root)]
    rows, problems = load(manifest_path, FILE_HEADER)
    sites, site_problems = load(sites_path, SITE_HEADER)
    fails += ["pairing: " + p for p in problems + site_problems]
    source = {rel(p) for p in tracked(layout.SOURCE, root)}
    copies = {rel(p) for p in tracked(layout.TARGET, root)} - {MANIFEST, SITES}
    by_path = {}
    for row in rows:
        if row["path"] in by_path:
            fails.append("pairing: %s has two manifest rows" % row["path"])
        by_path[row["path"]] = row
    ordered = [r["path"] for r in rows]
    if ordered != sorted(ordered):
        fails.append("pairing: %s is not sorted by path" % MANIFEST)
    for path, row in sorted(by_path.items()):
        statuses = row["status"].split(",")
        unknown = [s for s in statuses if s not in STATUSES]
        if unknown:
            fails.append("pairing: %s: unknown status %s" % (path, ",".join(unknown)))
        primary = {s for s in statuses if s in PRIMARY}
        if len(primary) != 1 and primary != {"manual", "rewritten"}:
            fails.append("pairing: %s: want one of %s, or manual with rewritten"
                         % (path, ", ".join(sorted(PRIMARY))))
        for s in TWINLESS:
            if s in statuses and not row["notes"]:
                fails.append("pairing: %s: a %s row names its reason" % (path, s))
        if "flagged" in statuses and not row["notes"]:
            fails.append("pairing: %s: a flagged row names its reason" % path)
        for item in filter(None, row["rules"].split(",")):
            name, _, count = item.rpartition(":")
            if not name or not count.isdigit() or int(count) < 1:
                fails.append("pairing: %s: malformed rule count %r" % (path, item))
    for path in sorted(source):
        row = by_path.get(path)
        if row is None:
            fails.append("pairing: examples/%s has no manifest row" % path)
        elif set(TWINLESS) & set(row["status"].split(",")):
            if path in copies:
                fails.append("pairing: %s is %s but has a twin" % (path, row["status"]))
        elif path not in copies:
            fails.append("pairing: examples/%s has no twin in %s/" % (path, layout.TARGET))
    for path in sorted(copies):
        row = by_path.get(path)
        if path not in source and (row is None or "new" not in row["status"].split(",")):
            fails.append("pairing: %s/%s has no original in examples/ and is not marked new"
                         % (layout.TARGET, path))
        if row is None:
            fails.append("pairing: %s/%s has no manifest row" % (layout.TARGET, path))
    for path in sorted(set(by_path) - source - copies):
        fails.append("pairing: manifest row %s names no file" % path)
    for path in sorted(source & copies):
        a = read_bytes(root, layout.SOURCE + "/" + path, fails)
        b = read_bytes(root, layout.TARGET + "/" + path, fails)
        if a is None or b is None:
            continue
        # An unchanged status means the twin is its original; a changed one,
        # that it is not.
        statuses = set(by_path[path]["status"].split(",")) if path in by_path else set()
        if statuses & UNCHANGED and a != b:
            fails.append("pairing: %s is %s but differs from its original"
                         % (path, ",".join(sorted(statuses & UNCHANGED))))
        if statuses & {"rewritten", "manual"} and a == b:
            fails.append("pairing: %s is marked changed but is its original byte for byte" % path)
        # XFAIL parity: a twin carries a marker line iff its original has the same one.
        if path.endswith(".saw"):
            if xfail_lines(a.decode("utf-8", "replace")) != xfail_lines(b.decode("utf-8", "replace")):
                fails.append("pairing: %s: the XFAIL markers differ between the twins" % path)
    # Site rows: counts agree with the file rows.
    counted = {}
    for s in sites:
        if s["status"] not in SITE_STATUSES:
            fails.append("pairing: %s:%s: unknown site status %s" % (s["path"], s["line"], s["status"]))
        if s["path"] not in by_path:
            fails.append("pairing: site row for %s, which has no file row" % s["path"])
        if s["status"] in ("rewritten", "manual", "reviewed"):
            key = (s["path"], s["rule"] if s["status"] == "rewritten"
                   else s["status"] + "." + s["rule"])
            counted[key] = counted.get(key, 0) + 1
        if s["status"] == "withheld" and not s["reason"]:
            fails.append("pairing: %s:%s: a withheld site names its reason" % (s["path"], s["line"]))
    declared = {}
    for path, row in by_path.items():
        for item in filter(None, row["rules"].split(",")):
            name, _, count = item.rpartition(":")
            if count.isdigit():
                declared[(path, name)] = int(count)
    for key in sorted(set(counted) | set(declared)):
        if counted.get(key, 0) != declared.get(key, 0):
            fails.append("pairing: %s: rule %s counts %d in %s but %d site rows"
                         % (key[0], key[1], declared.get(key, 0), MANIFEST, counted.get(key, 0)))
    return fails
