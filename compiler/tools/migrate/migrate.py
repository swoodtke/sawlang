#!/usr/bin/env python3
"""The one-shot migration of examples/ to tests/corpus/ (SL-418).

    python compiler/tools/migrate/migrate.py observe [--fresh] [--jobs N]
    python compiler/tools/migrate/migrate.py apply

`observe` runs the instrument over every entry and caches its records under
.build/migrate/runs/. `apply` reads them and writes tests/corpus/ with its two
manifests. A person's work is two tables beside this file: manual.tsv edits or
reviews single sites, and decisions.tsv records a verdict on a whole file (a
retirement, or the note on what a re-aimed file now tests).
"""
import argparse
import concurrent.futures
import os
import pickle
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import layout  # noqa: E402
import manifest  # noqa: E402
import mechanical  # noqa: E402
import observe  # noqa: E402
import pipeline  # noqa: E402
import scan  # noqa: E402

RUNS = os.path.join(layout.REPO, ".build", "migrate", "runs")


def entries(root=layout.REPO):
    out = []
    for path in layout.tracked(layout.SOURCE, root):
        if not path.endswith(".saw"):
            continue
        with open(os.path.join(root, path), encoding="utf-8", errors="replace") as fh:
            if layout.is_entry(fh.read()):
                out.append(path)
    return out


def cmd_observe(args):
    todo = entries()
    if args.files:
        todo = [p for p in todo if p in set(args.files)]
    results = observe.observe(todo, RUNS, args.jobs, fresh=args.fresh,
                              progress=lambda s: print(s, flush=True))
    counts = {}
    for records in results.values():
        s = observe.status_of(records).split(":")[0]
        counts[s] = counts.get(s, 0) + 1
    print("observed %d entries: %s" % (len(results), ", ".join(
        "%d %s" % (n, s) for s, n in sorted(counts.items()))))
    return 0


MANUAL = os.path.join(HERE, "manual.tsv")
MANUAL_HEADER = ("path", "line", "col", "rule", "old", "new", "rationale")


def unescape(text):
    out, i = [], 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            out.append({"n": "\n", "t": "\t", "\\": "\\"}.get(text[i + 1], text[i + 1]))
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def load_manual(path=MANUAL):
    """{examples path: [row]} of the hand migrations."""
    if not os.path.exists(path):
        return {}
    rows, problems = manifest.load(path, MANUAL_HEADER)
    if problems:
        raise SystemExit("\n".join(problems))
    return group_manual(rows, lambda p: layout.SOURCE + "/" + p)


def group_manual(rows, key):
    """{key(path): [row]}, each row unescaped, and each companion row (rule
    `+`) given its `parent`, the rule of the row before it."""
    out, parent = {}, None
    for r in rows:
        r = {k: unescape(v) for k, v in r.items()}
        r["line"], r["col"] = int(r["line"]), int(r["col"])
        if r["rule"] == pipeline.COMPANION:
            if parent is None or parent["path"] != r["path"]:
                raise SystemExit("%s:%d: a companion row follows no row of its file"
                                 % (r["path"], r["line"]))
            r["parent"] = parent["rule"]
        else:
            parent = r
        out.setdefault(key(r["path"]), []).append(r)
    return out


DECISIONS = os.path.join(HERE, "decisions.tsv")
DECISIONS_HEADER = ("path", "decision", "note")
# A decision names the primary status the file must come out with; `retired`
# files are not written at all.
DECISION_KINDS = {"retired", "manual", "reviewed", "flagged"}


def load_decisions(path=DECISIONS):
    """{examples path: (decision, note)}: a person's verdict on a whole file,
    recorded in its manifest row (SL-420)."""
    if not os.path.exists(path):
        return {}
    rows, problems = manifest.load(path, DECISIONS_HEADER)
    out = {}
    for r in rows:
        if r["decision"] not in DECISION_KINDS:
            problems.append("%s: %s: unknown decision %r" % (path, r["path"], r["decision"]))
        if not r["note"]:
            problems.append("%s: %s: a decision names its reason" % (path, r["path"]))
        key = layout.SOURCE + "/" + r["path"]
        if key in out:
            problems.append("%s: %s has two decisions" % (path, r["path"]))
        out[key] = (r["decision"], unescape(r["note"]))
    if problems:
        raise SystemExit("\n".join(problems))
    return out


def decided_row(row, decision, note):
    """The manifest row with the decision's note, or a SystemExit when the
    file did not come out with the decided status."""
    primary = [s for s in row["status"].split(",") if s in manifest.PRIMARY]
    if decision not in primary:
        raise SystemExit("decisions.tsv: %s is decided %s but came out %s"
                         % (row["path"], decision, row["status"]))
    row["notes"] = "; ".join(filter(None, [note, row["notes"]]))
    return row


def load_expected():
    """corpus_expected.tsv's rows, read by the grammar corpus's own loader."""
    import importlib.util
    path = os.path.join(layout.REPO, "compiler", "tests", "grammar", "corpus.py")
    sys.path.insert(0, os.path.dirname(path))
    spec = importlib.util.spec_from_file_location("grammar_corpus", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows, _ = module.load_expected()
    return rows


def run_job(job):
    res = pipeline.process(job)
    return res.path, res.text, res.statuses, res.row(), res.sites


WORK = os.path.join(layout.REPO, ".build", "migrate", "work")


def run_pool(jobs, n):
    """Each job's result, in job order, from `n` plain subprocess workers (a
    sandbox may refuse the semaphores multiprocessing needs)."""
    os.makedirs(WORK, exist_ok=True)
    n = max(1, min(n, len(jobs)))
    jobfile = os.path.join(WORK, "jobs.pickle")
    with open(jobfile, "wb") as fh:
        pickle.dump(jobs, fh)

    def work(k):
        out = os.path.join(WORK, "results.%d.pickle" % k)
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "worker", jobfile,
                            str(k), str(n), out], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("a migration worker failed:\n%s" % r.stderr[-4000:])
        with open(out, "rb") as fh:
            return pickle.load(fh)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        shares = list(pool.map(work, range(n)))
    results = [None] * len(jobs)
    for k, share in enumerate(shares):
        for m, result in enumerate(share):
            results[k + m * n] = result
    return results


def cmd_worker(args):
    with open(args.jobfile, "rb") as fh:
        jobs = pickle.load(fh)
    share = jobs[args.k::args.n]
    results = [run_job(job) for job in share]
    with open(args.out, "wb") as fh:
        pickle.dump(results, fh)
    return 0


def cmd_apply(args):
    passes = set(args.passes.split(","))
    obs = mechanical.Observations(RUNS)
    expected = load_expected()
    manual = load_manual() if "manual" in passes else {}
    decisions = load_decisions() if "manual" in passes else {}
    accessors = sorted(scan.accessor_names())
    jobs = []
    file_rows, site_rows = [], []
    for path in layout.tracked(layout.SOURCE):
        decision, note = decisions.get(path, (None, None))
        if decision == "retired":
            if path in manual:
                raise SystemExit("decisions.tsv: %s is retired but has manual rows" % path)
            file_rows.append({"path": manifest.rel(path), "status": "retired", "rules": "",
                              "notes": note})
            continue
        with open(os.path.join(layout.REPO, path), encoding="utf-8", newline="") as fh:
            text = fh.read()
        jobs.append({"path": path, "text": text, "passes": passes,
                     "windows": obs.windows.get(path, []), "closures": obs.closures.get(path, []),
                     "walked": sorted(obs.walked.get(path, set())), "accessors": accessors,
                     "expected": expected.get(path), "manual": manual.get(path)})
    target = os.path.join(layout.REPO, layout.TARGET)
    written = set()
    for path, text, _, row, sites in run_pool(jobs, args.jobs):
        out = os.path.join(layout.REPO, layout.target_of(path))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        written.add(os.path.realpath(out))
        if path in decisions:
            row = decided_row(row, *decisions[path])
        file_rows.append(row)
        site_rows.extend(sites)
    for dirpath, _, names in os.walk(target):
        for name in names:
            p = os.path.realpath(os.path.join(dirpath, name))
            if p not in written and name not in (manifest.MANIFEST, manifest.SITES):
                os.remove(p)
    manifest.write(layout.REPO, file_rows, site_rows)
    counts = {}
    for row in file_rows:
        for s in row["status"].split(","):
            counts[s] = counts.get(s, 0) + 1
    print("migrated %d files: %s" % (len(file_rows), ", ".join(
        "%d %s" % (n, s) for s, n in sorted(counts.items()))))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ob = sub.add_parser("observe")
    ob.add_argument("--fresh", action="store_true")
    ob.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ob.add_argument("files", nargs="*")
    ap_apply = sub.add_parser("apply")
    ap_apply.add_argument("--passes", default="mechanical,grammar,manual")
    ap_apply.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    wk = sub.add_parser("worker")
    wk.add_argument("jobfile")
    wk.add_argument("k", type=int)
    wk.add_argument("n", type=int)
    wk.add_argument("out")
    args = ap.parse_args(argv)
    if args.cmd == "observe":
        return cmd_observe(args)
    if args.cmd == "apply":
        return cmd_apply(args)
    if args.cmd == "worker":
        return cmd_worker(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
