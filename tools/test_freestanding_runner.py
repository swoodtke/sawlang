#!/usr/bin/env python3
"""tools/freestanding_runner.py's verdicts on its prerequisites, against stub tools.

    python tools/test_freestanding_runner.py

The freestanding suite skips, and passes, only when QEMU, ld.lld or a clang for
the target is known absent: not on PATH, or no clang `build.pick_clang` would
choose. When their presence cannot be determined it fails (exit 4): no PATH at
all, a tool on PATH that does not answer `--version`, or a `SAWC_CLANG` naming
no usable clang. Each case runs the runner's `--tools` decision with stub tools
first on a PATH that holds no real ones, with `HOMEBREW_PREFIX` naming no
Homebrew, so nothing is built or booted.

It also holds the runner's soft-float list, the routines a case object
defines itself, equal to the routines LANGUAGE_SPEC.md's Profiles paragraph
names; requires the symbol check to refuse an object that leaves a
soft-float routine undefined; recomputes every row of
`cases/integer_vectors.saw`, the integer helpers' vectors, from its operands;
and holds `cases/soft_float_vectors.saw`'s `CHECKSUMS` equal to the checksums
of `compiler/tests/run/softfloat/vectors.txt`, in the runner's order.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))
sys.path.insert(0, HERE)

import build  # noqa: E402
import freestanding_runner  # noqa: E402

sys.path.insert(0, os.path.join(REPO, "compiler", "tests", "run", "softfloat"))
import generate as softfloat_vectors  # noqa: E402

RUNNER = os.path.join(HERE, "freestanding_runner.py")
OUT = os.path.join(build.BUILD_DIR, "test-freestanding-runner")
ARCHES = [a for a in freestanding_runner.ARCHES if not a["off"]]
# The runner probes the arches in order, so the first one's QEMU is the one an
# absence or a refusal is reported for.
QEMU = ARCHES[0]["qemu"]
# Where `build.homebrew_clang()` looks, pointed at nothing: a clang outside
# PATH would otherwise answer every case that has the stubs alone.
NO_HOMEBREW = os.path.join(OUT, "no-homebrew")

ANSWERS = "#!/bin/sh\necho '%s 0.0 (stub)'\nexit 0\n"
REFUSES = "#!/bin/sh\necho '%s: cannot run here' >&2\nexit 1\n"
EVERY_QEMU = dict((a["qemu"], ANSWERS) for a in ARCHES)


def present(over=None):
    """ld.lld and every arch's QEMU answering, then the stubs of `over` in
    their place or beside them."""
    found = {"ld.lld": ANSWERS}
    found.update(EVERY_QEMU)
    found.update(over or {})
    return found


# (case, {stub name: body}, PATH entries after the stubs or None for no PATH,
# SAWC_CLANG, the exit status, text the output holds, whether it says SKIPPED).
# `{real}` in SAWC_CLANG is a clang on this machine that compiles for every
# arch; a case naming it is passed over where there is none.
CASES = (
    ("no ld.lld", {}, [], None, 0, "ld.lld is not on PATH", True),
    ("no QEMU", {"ld.lld": ANSWERS}, [], None, 0, "%s is not on PATH" % QEMU, True),
    ("no clang", present(), [], None, 0, "no clang compiles for", True),
    ("a clang without the target", present({"clang": REFUSES}), [], None, 0, "does not compile opaque-pointer IR",
     True),
    ("ld.lld does not answer", {"ld.lld": REFUSES}, [], None, 4, "so whether it runs is unknown", False),
    ("QEMU does not answer", present({QEMU: REFUSES}), [], None, 4, "so whether it runs is unknown", False),
    ("no PATH", {}, None, None, 4, "PATH is not set", False),
    ("SAWC_CLANG names nothing", present(), [], "/nonexistent/clang", 4, "SAWC_CLANG names no clang", False),
    ("all present", present(), [], "{real}", 0, "every prerequisite is present", False),
)


def run_case(name, stubs, after, sawc_clang):
    """(exit status, output) of `--tools` under one set of stubs."""
    bin_dir = os.path.join(OUT, name.replace(" ", "-"))
    shutil.rmtree(bin_dir, ignore_errors=True)
    os.makedirs(bin_dir)
    for tool, body in stubs.items():
        path = os.path.join(bin_dir, tool)
        with open(path, "w") as fh:
            fh.write(body % tool)
        os.chmod(path, 0o755)
    env = dict(os.environ)
    env.pop("PATH", None)
    env.pop("SAWC_CLANG", None)
    env["HOMEBREW_PREFIX"] = NO_HOMEBREW
    if after is not None:
        env["PATH"] = os.pathsep.join([bin_dir] + after)
    if sawc_clang is not None:
        env["SAWC_CLANG"] = sawc_clang
    r = subprocess.run([sys.executable, RUNNER, "--tools"], cwd=REPO, env=env, capture_output=True, text=True,
                       timeout=180)
    return r.returncode, r.stdout + r.stderr


SPEC = os.path.join(REPO, "LANGUAGE_SPEC.md")
# The opening of the Profiles paragraph that lists the soft-float routines.
SOFT_FLOAT_PARAGRAPH = "On a target with no floating-point unit"


def soft_float_problems():
    """Why the runner's soft-float list differs from the spec's, or why the
    symbol check lets an object leave a soft-float routine undefined, or []."""
    with open(SPEC, encoding="utf-8") as fh:
        paragraphs = [" ".join(p.split()) for p in fh.read().split("\n\n")]
    found = [p for p in paragraphs if p.startswith(SOFT_FLOAT_PARAGRAPH)]
    if len(found) != 1:
        return ["LANGUAGE_SPEC.md has %d paragraphs opening %r, not one" % (len(found), SOFT_FLOAT_PARAGRAPH)]
    spec = set(re.findall(r"`(__\w+)`", found[0]))
    runner = set(freestanding_runner.SOFT_FLOAT_ROUTINES)
    problems = []
    if runner != spec:
        problems.append("the runner's soft-float list differs from the spec's: only the runner has %s, only the "
                        "spec has %s" % (sorted(runner - spec), sorted(spec - runner)))
    case = {"name": "stub"}
    for arch in ARCHES:
        seams = {"__saw_rt_write", "fs_console_write"}
        if freestanding_runner.undefined_problem(case, arch, seams) is not None:
            problems.append("%s: the symbol check refuses an object leaving only seams undefined" % arch["name"])
        for name in ("__adddf3", "__floatundidf", "__extendsfdf2"):
            said = freestanding_runner.undefined_problem(case, arch, seams | {name})
            if said is None or name not in said:
                problems.append("%s: the symbol check lets an object leave %s undefined (%s)"
                                % (arch["name"], name, said))
    return problems


SOFT_FLOAT_CASE = os.path.join(freestanding_runner.CASES_DIR, "soft_float_vectors.saw")


def checksum_problems():
    """Why `cases/soft_float_vectors.saw`'s `CHECKSUMS` differ from the
    soft-float vectors' own checksums, in the runner's order, or []."""
    with open(SOFT_FLOAT_CASE, encoding="utf-8") as fh:
        text = fh.read()
    found = re.search(r"static CHECKSUMS: \[UInt64; ROUTINE_COUNT\] = \[(.*?)\]", text, re.S)
    if not found:
        return ["%s: no CHECKSUMS table" % os.path.relpath(SOFT_FLOAT_CASE, REPO)]
    stated = [int(t.replace("_", ""), 16) for t in re.findall(r"0x([0-9A-Fa-f_]+)", found.group(1))]
    with open(softfloat_vectors.VECTORS, encoding="utf-8") as fh:
        sums = softfloat_vectors.checksums(fh.read())
    order = [routine[2:] for routine in freestanding_runner.SOFT_FLOAT_ROUTINES]
    if sorted(order) != sorted(sums):
        return ["the runner's soft-float routines %s are not the vectors' %s" % (order, sorted(sums))]
    want = [sums[name] for name in order]
    if stated != want:
        return ["%s: CHECKSUMS %s, and the vectors' checksums in the runner's order are %s"
                % (os.path.relpath(SOFT_FLOAT_CASE, REPO), ["0x%016X" % v for v in stated],
                   ["0x%016X" % v for v in want])]
    return []


VECTORS = os.path.join(freestanding_runner.CASES_DIR, "integer_vectors.saw")
_MASK = (1 << 64) - 1


def _signed(v):
    v &= _MASK
    return v - (1 << 64) if v >> 63 else v


def _unsigned_answer(n, d):
    """C's quotient and remainder, and the helpers' answer for a zero divisor:
    an all-ones quotient and a zero remainder."""
    return (_MASK, 0) if d == 0 else (n // d, n % d)


def _signed_answer(n, d):
    """C's truncating quotient and dividend-signed remainder, at 64 bits; the
    helpers' zero-divisor answer; and `Int64.min / -1` wrapped."""
    if d == 0:
        return (-1 if n >= 0 else 1), 0
    q = abs(n) // abs(d)
    q = -q if (n < 0) != (d < 0) else q
    return _signed(q), _signed(n - q * d)


def _rows(text, name, width):
    """The rows of `integer_vectors.saw`'s table `name`, `width` numbers each."""
    found = re.search(r"static %s: \[\w+; \d \* \w+\] = \[(.*?)\n\]" % name, text, re.S)
    if not found:
        return None
    numbers = [int(t.replace("_", ""), 0) for t in re.findall(r"-?(?:0x[0-9A-Fa-f_]+|[0-9_]+)", found.group(1))]
    return [numbers[k:k + width] for k in range(0, len(numbers), width)]


def vector_problems():
    """Why a row of `cases/integer_vectors.saw` disagrees with the answer
    computed here, or []: each table holds as many rows as its count says."""
    with open(VECTORS, encoding="utf-8") as fh:
        text = fh.read()
    problems = []
    tables = (("UNSIGNED_DIVISION", 4, lambda r: list(_unsigned_answer(r[0], r[1]))),
              ("SIGNED_DIVISION", 4, lambda r: list(_signed_answer(r[0], r[1]))),
              ("SHIFTS", 5, lambda r: [(r[0] << r[1]) & _MASK, r[0] >> r[1], (_signed(r[0]) >> r[1]) & _MASK]))
    for name, width, answer in tables:
        rows = _rows(text, name, width)
        count = re.search(r"static %s_ROWS: Int = (\d+)" % (name if name != "SHIFTS" else "SHIFT"), text)
        if rows is None or count is None or len(rows) != int(count.group(1)) or any(len(r) != width for r in rows):
            problems.append("%s: the table %s does not hold its stated count of %d-number rows"
                            % (os.path.relpath(VECTORS, REPO), name, width))
            continue
        for k, row in enumerate(rows):
            if row[2:] != answer(row):
                problems.append("%s: %s row %d is %r, and the answer computed here is %r"
                                % (os.path.relpath(VECTORS, REPO), name, k, row[2:], answer(row)))
    return problems


def main():
    real, _ = build.pick_clang(ARCHES[0]["triple"], None)
    if real is not None and not all(build.clang_capable(real, a["triple"]) for a in ARCHES):
        real = None
    failures = []
    ran = 0
    for name, stubs, after, sawc_clang, want_status, text, skipped in CASES:
        if sawc_clang == "{real}":
            if real is None:
                print("freestanding runner: passed over %r: no clang here compiles for every one of %s"
                      % (name, ", ".join(a["triple"] for a in ARCHES)))
                continue
            sawc_clang = real
        ran += 1
        status, said = run_case(name, stubs, after, sawc_clang)
        if status != want_status or text not in said:
            failures.append("%s: `--tools` exits %d, not %d, or does not say %r: %s"
                            % (name, status, want_status, text, said.strip()[:400]))
        if skipped and "SKIPPED" not in said:
            failures.append("%s: passes without saying it SKIPPED: %s" % (name, said.strip()[:400]))
        if not skipped and "SKIPPED" in said:
            failures.append("%s: says it SKIPPED: %s" % (name, said.strip()[:400]))
    failures += soft_float_problems()
    failures += vector_problems()
    failures += checksum_problems()
    for failure in failures:
        print(failure)
    print("freestanding runner: %s: %d stub cases, the soft-float list and symbol check, the integer helpers' "
          "vectors, the soft-float checksums" % ("FAIL (%d)" % len(failures) if failures else "ok", ran))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
