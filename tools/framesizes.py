#!/usr/bin/env python3
"""Coroutine frame-size sweep and overlay analysis (design 163).

Drives `sawc --emit-frame-layout` over a corpus (examples/, blade, the SOS
kernel, libs) and reports two things:

  1. REALITY. What every monomorphized `__Frame_*` costs today under the
     flat-frame model: total size, own bytes, embedded-child bytes, the
     distribution across the corpus, and the top offenders.

  2. THE HYPOTHETICAL. What the same frames would cost if the embedded child
     sub-frames were OVERLAID — one shared slot sized by the high-water mark
     instead of one distinct offset per call site. The transform emits each
     child's storage live in exactly ONE resume state (the drive block), which
     `--emit-frame-layout` records per child, so the overlay size is a
     bottom-up recurrence:

         overlay(F) = layout(F's own fields, with the contiguous run of
                             `__subN` fields replaced by a single slot of
                             size  = max over children c of overlay(c)
                             align = max over children c of align(c))

     The tool CHECKS the premise rather than assuming it: if two children of
     one frame ever shared a live state, the max would be wrong, and that is
     reported as a violation.

Usage:
    ./.venv/bin/python tools/framesizes.py            # full sweep, summary
    ./.venv/bin/python tools/framesizes.py --json OUT # also dump raw data
    ./.venv/bin/python tools/framesizes.py --top 25
    ./.venv/bin/python tools/framesizes.py --only examples

Analysis only. Nothing here changes what the compiler emits.
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO, "sawc", "sawc.py")
PY = sys.executable

SUB_PREFIX = "__sub"
FRAME_PREFIX = "__Frame_"


# --------------------------------------------------------------------------
# Target discovery
# --------------------------------------------------------------------------

def _compile_flags(path):
    """The `// COMPILE-FLAGS:` directive a corpus example may carry, with the
    same `{TESTDIR}` expansion the test runner does."""
    try:
        with open(path, "r") as f:
            for line in f:
                if "// COMPILE-FLAGS:" in line:
                    raw = line.split("// COMPILE-FLAGS:")[1].strip()
                    raw = raw.replace("{TESTDIR}", os.path.dirname(path))
                    flags = raw.split()
                    # An example that drives a DIFFERENT emitter (docs/AST/IR)
                    # would answer with that emitter's output, not a frame
                    # report — those flags are checked ahead of ours.
                    if any(f.startswith("--emit-") for f in flags):
                        return None
                    return flags
                if "// EXPECT: skip" in line:
                    return None
    except OSError:
        return []
    return []


def discover(groups):
    """(group, label, source, extra_flags) for everything worth compiling."""
    targets = []
    if "examples" in groups:
        ex = os.path.join(REPO, "examples")
        for name in sorted(os.listdir(ex)):
            if not name.endswith(".saw"):
                continue
            path = os.path.join(ex, name)
            flags = _compile_flags(path)
            if flags is None:
                continue
            targets.append(("examples", name[:-4], path, flags))
    if "blade" in groups:
        main = os.path.join(REPO, "blade", "src", "main.saw")
        if os.path.exists(main):
            targets.append(("blade", "blade", main, [
                "--module-path", f"toml={os.path.join(REPO, 'libs', 'toml', 'src')}",
                "--module-path",
                f"semver={os.path.join(REPO, 'libs', 'semver', 'src')}"]))
    # The `sos` measurement group left with the kernel (design 238 unit 5,
    # Aug 28 2026 — sos/ lives in the sawos repository now). sawos can regrow
    # the group beside its own harness if the measurement is wanted there.
    return targets


# --------------------------------------------------------------------------
# Sweep
# --------------------------------------------------------------------------

def run_one(target):
    group, label, path, flags = target
    cmd = [PY, SAWC, path, "--emit-frame-layout"] + list(flags)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return group, label, path, None, "timeout"
    if r.returncode != 0:
        first = (r.stderr or r.stdout or "").strip().splitlines()
        return group, label, path, None, (first[0][:120] if first else "failed")
    try:
        report = json.loads(r.stdout)
    except json.JSONDecodeError:
        return group, label, path, None, "unparseable report"
    if not isinstance(report, dict) or "frames" not in report:
        return group, label, path, None, "not a frame report"
    return group, label, path, report, None


def sweep(targets, jobs):
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(run_one, targets))


# --------------------------------------------------------------------------
# Overlay model
# --------------------------------------------------------------------------

def _align_up(n, a):
    return n if a <= 1 else ((n + a - 1) // a) * a


def _relayout(own_fields, slot_size, slot_align, slot_at):
    """Lay out a frame whose contiguous `__subN` run is replaced by one slot.

    `own_fields` is the non-sub field list in declaration order; `slot_at` is
    the index in that list where the sub-run began. Reproduces LLVM's
    non-packed struct layout: each field aligned to its ABI alignment, the
    whole rounded up to the max alignment."""
    offset = 0
    max_align = 1
    seq = list(own_fields[:slot_at])
    if slot_size > 0:
        seq.append({"size": slot_size, "align": slot_align})
    seq.extend(own_fields[slot_at:])
    for f in seq:
        a = f["align"] or 1
        max_align = max(max_align, a)
        offset = _align_up(offset, a)
        offset += f["size"]
    return _align_up(offset, max_align), max_align


class Program:
    """One compiled program's frame set, with the overlay recurrence solved."""

    def __init__(self, label, group, report):
        self.label = label
        self.group = group
        self.frames = report["frames"]
        self.violations = []
        self.disagreements = [n for n, f in self.frames.items()
                              if not f.get("layout_agrees", True)]
        self._overlay = {}
        self._overlay_align = {}
        for name in self.frames:
            self._solve(name, set())

    def _check_live_sets(self, name, frame):
        """The premise: no two children of one frame are live in the same
        resume state. Records a violation instead of silently mis-sizing."""
        seen = {}
        for f in frame["fields"]:
            if f["kind"] != "sub":
                continue
            st = f.get("live_state")
            if st is None:
                self.violations.append(f"{name}.{f['name']}: no live state recorded")
                continue
            if st in seen:
                self.violations.append(
                    f"{name}: {seen[st]} and {f['name']} share live state {st}")
            seen[st] = f["name"]

    def _solve(self, name, stack):
        if name in self._overlay:
            return self._overlay[name]
        frame = self.frames.get(name)
        if frame is None:
            # A callee frame outside this report (should not happen: the
            # transform embeds by value, so every callee is registered).
            return 0
        if name in stack:
            self.violations.append(f"{name}: cycle in the embed graph")
            return frame["size"]
        stack = stack | {name}
        self._check_live_sets(name, frame)

        own = []
        slot_at = None
        slot_size = 0
        slot_align = 1
        for f in frame["fields"]:
            if f["kind"] == "sub":
                if slot_at is None:
                    slot_at = len(own)
                child = f.get("callee")
                slot_size = max(slot_size, self._solve(child, stack))
                slot_align = max(slot_align,
                                 self._overlay_align.get(child, f["align"] or 1))
            else:
                own.append(f)
        if slot_at is None:
            slot_at, slot_size, slot_align = len(own), 0, 1
        size, align = _relayout(own, slot_size, slot_align, slot_at)
        self._overlay[name] = size
        self._overlay_align[name] = align
        return size

    def rows(self):
        for name, f in self.frames.items():
            yield {
                "program": self.label,
                "group": self.group,
                "frame": name,
                "today": f["size"],
                "overlay": self._overlay.get(name, f["size"]),
                "own_bytes": f["own_bytes"],
                "sub_bytes": f["sub_bytes"],
                "children": len(f["children"]),
                "states": f.get("states"),
                "spawn_root": f.get("is_spawn_root", False),
                "method": f.get("is_method", False),
            }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def pct(part, whole):
    return 0.0 if not whole else 100.0 * part / whole


def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0
    k = (len(sorted_vals) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def summarize(rows, programs, failures, top, out):
    w = out.write
    total_today = sum(r["today"] for r in rows)
    total_overlay = sum(r["overlay"] for r in rows)
    sizes = sorted(r["today"] for r in rows)

    w("=" * 74 + "\n")
    w("FRAME SIZE SWEEP (design 163)\n")
    w("=" * 74 + "\n")
    w(f"programs compiled : {len(programs)}"
      f"   (failed/skipped: {len(failures)})\n")
    w(f"frames measured   : {len(rows)}"
      f"   (distinct frame names: {len({r['frame'] for r in rows})})\n")
    nested = [r for r in rows if r["children"]]
    w(f"frames with embeds: {len(nested)} "
      f"({pct(len(nested), len(rows)):.0f}%)\n\n")

    w("-- today's sizes (bytes, per monomorphized frame) --\n")
    for label, p in [("min", 0), ("p50", 50), ("p90", 90), ("p99", 99),
                     ("max", 100)]:
        w(f"  {label:>4}: {percentile(sizes, p):>9.0f}\n")
    w(f"  mean: {total_today / max(1, len(rows)):>9.1f}\n")
    w(f"   sum: {total_today:>9}\n\n")

    w("-- overlay hypothetical (max over simultaneously-live children) --\n")
    w(f"  corpus bytes today   : {total_today}\n")
    w(f"  corpus bytes overlaid: {total_overlay}\n")
    w(f"  saving               : {total_today - total_overlay} "
      f"({pct(total_today - total_overlay, total_today):.1f}%)\n")
    shrunk = [r for r in rows if r["overlay"] < r["today"]]
    w(f"  frames that shrink   : {len(shrunk)} / {len(rows)} "
      f"({pct(len(shrunk), len(rows)):.0f}%)\n")
    if shrunk:
        ratios = sorted(r["overlay"] / r["today"] for r in shrunk)
        w(f"  of those, median size after overlay: "
          f"{percentile(ratios, 50) * 100:.0f}% of today\n")
        w(f"  best case                         : "
          f"{ratios[0] * 100:.0f}% of today\n")
    w("\n")

    roots = [r for r in rows if r["spawn_root"]]
    if roots:
        rt = sum(r["today"] for r in roots)
        ro = sum(r["overlay"] for r in roots)
        w("-- per-task spawn cost (spawn-root frames; each is a heap box) --\n")
        w(f"  spawn roots: {len(roots)}\n")
        w(f"  today  : mean {rt / len(roots):.0f} B, max "
          f"{max(r['today'] for r in roots)} B\n")
        w(f"  overlay: mean {ro / len(roots):.0f} B, max "
          f"{max(r['overlay'] for r in roots)} B "
          f"({pct(rt - ro, rt):.0f}% smaller)\n\n")

    w(f"-- top {top} offenders by size today --\n")
    w(f"  {'bytes':>7} {'overlay':>8} {'save':>6} {'kids':>4}  frame  (program)\n")
    for r in sorted(rows, key=lambda r: -r["today"])[:top]:
        w(f"  {r['today']:>7} {r['overlay']:>8} "
          f"{pct(r['today'] - r['overlay'], r['today']):>5.0f}% "
          f"{r['children']:>4}  {r['frame']}  ({r['program']})\n")
    w("\n")

    w("-- by group --\n")
    for g in sorted({r["group"] for r in rows}):
        gr = [r for r in rows if r["group"] == g]
        gt = sum(r["today"] for r in gr)
        go = sum(r["overlay"] for r in gr)
        w(f"  {g:<10} frames {len(gr):>5}  today {gt:>8} B  "
          f"overlay {go:>8} B  saving {pct(gt - go, gt):>5.1f}%\n")
    w("\n")

    viol = [(p.label, v) for p in programs for v in p.violations]
    dis = [(p.label, n) for p in programs for n in p.disagreements]
    w("-- premise checks --\n")
    w(f"  frames where the C-layout walk disagreed with LLVM: {len(dis)}\n")
    w(f"  frames where two children shared a live state     : {len(viol)}\n")
    for label, v in viol[:10]:
        w(f"      {label}: {v}\n")
    w("\n")
    if failures:
        w(f"-- {len(failures)} target(s) did not compile (rejection tests, "
          f"missing deps) --\n")
        for label, why in failures[:8]:
            w(f"  {label}: {why}\n")
        if len(failures) > 8:
            w(f"  ... and {len(failures) - 8} more\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", default=[],
                    choices=["examples", "blade", "sos"],
                    help="Restrict the sweep to a group (repeatable).")
    ap.add_argument("--top", type=int, default=20, help="Top-offender rows.")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--json", metavar="PATH", help="Dump every measured row.")
    ap.add_argument("--frame", metavar="NAME",
                    help="Print one frame's full field layout and exit.")
    args = ap.parse_args()

    groups = args.only or ["examples", "blade", "sos"]
    targets = discover(groups)
    if not targets:
        print("no targets found", file=sys.stderr)
        return 1
    print(f"sweeping {len(targets)} target(s) with {args.jobs} jobs...",
          file=sys.stderr)
    results = sweep(targets, args.jobs)

    programs, failures, rows = [], [], []
    for group, label, _path, report, err in results:
        if report is None:
            failures.append((label, err))
            continue
        if not report["frames"]:
            continue
        p = Program(label, group, report)
        programs.append(p)
        rows.extend(p.rows())

    if args.frame:
        for group, label, _p, report, err in results:
            if report and args.frame in report["frames"]:
                print(f"# {label}")
                print(json.dumps(report["frames"][args.frame], indent=2))
                return 0
        print(f"frame {args.frame} not found", file=sys.stderr)
        return 1

    if not rows:
        print("no frames measured (nothing in the sweep suspends)")
        return 0

    summarize(rows, programs, failures, args.top, sys.stdout)
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"rows": rows,
                       "failures": failures}, f, indent=2, sort_keys=True)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
