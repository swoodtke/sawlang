"""The mechanical pass: the instrument's records, per file, through the rules."""
import glob
import json
import os

import edits
import rules


class Observations:
    """Every run's records for the source corpus, deduplicated per site."""

    def __init__(self, runs_dir):
        self.windows, self.closures, self.walked = {}, {}, {}
        self.lowered, self.statuses = set(), {}
        seen_w, seen_c = set(), set()
        for p in sorted(glob.glob(os.path.join(runs_dir, "*.json"))):
            with open(p, encoding="utf-8") as fh:
                records = json.load(fh)
            status = next((r.get("status") for r in records if r.get("kind") == "status"), "missing")
            entry = os.path.basename(p)[:-len(".json")].replace("__", "/")
            self.statuses[entry] = status
            for r in records:
                f = r.get("file") or ""
                if not f.startswith("examples/"):
                    continue
                kind = r.get("kind")
                if kind == "window":
                    key = (f, r["line"], r["col"], r["caller"], bool(r.get("nested_outer")))
                    if key not in seen_w:
                        seen_w.add(key)
                        self.windows.setdefault(f, []).append(r)
                elif kind == "closure":
                    key = (f, r["line"], r["col"], r["arg_index"])
                    if key not in seen_c:
                        seen_c.add(key)
                        self.closures.setdefault(f, []).append(r)
                elif kind == "walked":
                    self.walked.setdefault(f, set()).add((r["line"], r["col"]))
                    if status == "stopped-after-places":
                        self.lowered.add(f)


def run(path, text, obs, meta):
    """(plan, None) for one file, or (None, why) for a text the lexer refuses."""
    try:
        src = edits.Source(text)
    except Exception as e:  # noqa: BLE001 - a text the lexer refuses has no sites to place
        return None, "lex: %s" % e
    plan = rules.plan_file(path, src, obs.windows.get(path, []), obs.closures.get(path, []), meta)
    for s in plan.sites:
        s.before = src.line_text(s.line).strip()
    return plan, None
