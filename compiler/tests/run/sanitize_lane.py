#!/usr/bin/env python3
"""The sanitizer lane: the coroutine programs built under AddressSanitizer
and held to their plain builds, and an overlap injected past the verifier
reported at its access (SL:coroutines B3, risk R2).

    python compiler/tests/run/sanitize_lane.py [NAME...]

`compiler/tests/run.py` runs `run()` as its `sanitize` step. Each case is one
of the run lane's `coro_*` programs that is not due, its offload pins
(`OFFLOAD_PINS`), or a probe of `probes/` named by `PROBE_PATTERNS` that states its
output (`stated` or `panics`). Each is built at -O0 twice, plainly and with
`sawc2 build --sanitize address`, which stamps `sanitize_address` on every
function and poisons each lowered frame's values outside the lifetimes rule 5
recomputes; it passes when the sanitized binary prints the same bytes on
standard output and on standard error, where a panic goes, and exits with the
same status as the plain one, and AddressSanitizer reports nothing. Leak
detection is off: the lane checks frame lifetimes, and a
leak is no frame access.

The injection: `compiler/tests/coro/inject/asan_inject.saw`, built and run,
lowers `asan_overlap.saw` for a sanitizing build, moves `late` onto
`early`'s offset, requires the verifier's rule-5 report, and writes the
refused program's `.ll` anyway; linked under AddressSanitizer
(`build.link_module`), it must abort with a `use-after-poison` read in
`keep`'s resume function, before the print that read feeds.
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(REPO, "tools"))

import build  # noqa: E402
import gate_jobs  # noqa: E402
import run_lane  # noqa: E402

OUT = os.path.join(REPO, ".build", "sanitize-lane")
# The run lane's programs that hold a `blocking` extern's offload.
OFFLOAD_PINS = ("offload_cancel_waits_for_the_call", "offload_start_refused", "suspend_blocking_main")
PROBE_KINDS = ("stated", "panics")
# The probes the lane builds: the thread and coroutine probes, the generic
# defaults, where a value computed at another width than its slot's is a stack
# overwrite (SL-830), and the conditional lends, whose lent reference is read
# out of an Optional only on the present path (SL-686).
PROBE_PATTERNS = ("thread_*.saw", "coro_*.saw", "generic_default_*.saw", "conditional_lend_*.saw")
INJECTOR = os.path.join(TESTS, "coro", "inject", "asan_inject.saw")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 60
# The lane checks frame accesses; LeakSanitizer, on by default on Linux,
# would fail a program for a leak, which is no frame access. A resume
# function's stack slots die each time it returns `Pending`, so a value read
# from one after a suspension is a stack use after return, which ASan reports
# only with this detection on (SL-805).
ASAN_OPTIONS = "detect_leaks=0:detect_stack_use_after_return=1"
REPORT = "ERROR: AddressSanitizer"


def rel(path):
    return os.path.relpath(path, REPO)


def cases(names=None):
    """The programs the lane builds, in name order: the run lane's `coro_*`
    programs and offload pins that are not due, then the probes
    `PROBE_PATTERNS` names that state their output."""
    found = [src for src in sorted(glob.glob(os.path.join(HERE, "coro_*.saw")))
             + [os.path.join(HERE, name + ".saw") for name in OFFLOAD_PINS]
             if run_lane.headers(src)[0] is None]
    found.sort()
    probes = [src for pattern in PROBE_PATTERNS
              for src in glob.glob(os.path.join(run_lane.PROBES, pattern))]
    for src in sorted(probes):
        if run_lane.probe_header(src).get("probe", [None])[0] in PROBE_KINDS:
            found.append(src)
    if names:
        found = [src for src in found if os.path.splitext(os.path.basename(src))[0] in names]
    return found


def build_one(src, sanitize):
    """sawc2's -O0 build of `src`, sanitized or not: (linked, binary, what it
    printed)."""
    name = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(OUT, name + (".asan" if sanitize else ".plain"))
    flags = ["--sanitize", "address"] if sanitize else []
    r = subprocess.run([build.SAWC2, "build", "-O0", "--std-root", "std"] + flags + [rel(src), "-o", out],
                       cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    return r.returncode == 0, out, (r.stdout + r.stderr).strip()


def execute(binary):
    """(exit status, standard output, standard error), the status None on a
    timeout."""
    env = dict(os.environ, ASAN_OPTIONS=ASAN_OPTIONS)
    try:
        r = subprocess.run([binary], cwd=OUT, capture_output=True, timeout=RUN_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return None, b"", b""
    return r.returncode, r.stdout, r.stderr


def check_case(src):
    """The failures of one program."""
    where = "sanitize %s" % rel(src)
    builds = []
    for sanitize in (False, True):
        ok, binary, log = build_one(src, sanitize)
        if not ok or log:
            return ["%s: sawc2 %s%s: %s" % (where, "builds it but prints" if ok else "does not build it",
                                           " under --sanitize address" if sanitize else "", log[:300])]
        builds.append(binary)
    code_plain, out_plain, err_plain = execute(builds[0])
    code_asan, out_asan, err_asan = execute(builds[1])
    if code_plain is None or code_asan is None:
        return ["%s: a binary timed out (plain %s, sanitized %s)"
                % (where, "timed out" if code_plain is None else "ran",
                   "timed out" if code_asan is None else "ran")]
    failures = []
    text = err_asan.decode("utf-8", "replace")
    if REPORT in text:
        start = text.index(REPORT)
        failures.append("%s: AddressSanitizer reports: %s" % (where, " | ".join(
            line.strip() for line in text[start:].split("\n")[:4])))
    elif err_asan != err_plain:
        # A panic's message is on standard error, so a sanitized build that
        # reports nothing must say there what the plain build says.
        failures.append("%s: standard error differs from the plain build: %s"
                        % (where, run_lane.first_difference(err_asan, err_plain)))
    if code_asan != code_plain:
        failures.append("%s: exit %d sanitized, %d plain" % (where, code_asan, code_plain))
    if out_asan != out_plain:
        failures.append("%s: output differs from the plain build: %s"
                        % (where, run_lane.first_difference(out_asan, out_plain)))
    return failures


def check_injection():
    """The failures of the overlap injection (module docstring)."""
    exe = os.path.join(OUT, "asan_inject")
    ok, log = build.build_program(INJECTOR, exe)
    if not ok:
        return ["sanitize injection: %s does not compile: %s" % (rel(INJECTOR), log[:300])]
    ll = os.path.join(OUT, "asan_overlap.injected.ll")
    binary = os.path.join(OUT, "asan_overlap.injected")
    if os.path.exists(ll):
        os.remove(ll)
    r = subprocess.run([exe, ll, build.host_triple()], cwd=REPO, capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    if r.returncode != 0:
        return ["sanitize injection: %s exits %d: %s" % (rel(INJECTOR), r.returncode,
                                                         (r.stdout + r.stderr).strip()[:300])]
    ok, log = build.link_module(ll, binary, sanitize=True)
    if not ok:
        return ["sanitize injection: the injected module does not link: %s" % log[:300]]
    code, out, err = execute(binary)
    text = err.decode("utf-8", "replace")
    frames = [line.strip() for line in text.split("\n") if line.strip().startswith("#0 ")]
    if code in (0, None) or "AddressSanitizer: use-after-poison" not in text or "READ of size 8" not in text \
            or not frames or "in saw resume asan_overlap.keep(" not in frames[0] or b"late" in out:
        return ["sanitize injection: exit %s, not a use-after-poison read in `keep`'s resume function before "
                "its print: %s" % (code, " | ".join(text.strip().split("\n")[:4]) or out[:200])]
    return []


def run(names=None):
    """(failures, counts) of the lane, or of the cases `names` names."""
    os.makedirs(OUT, exist_ok=True)
    srcs = cases(names)
    failures = []
    counts = {}
    for src, found in zip(srcs, gate_jobs.map_ordered(check_case, srcs)):
        failures.extend(found)
        if not found:
            counts["sanitized programs matching their plain build"] = \
                counts.get("sanitized programs matching their plain build", 0) + 1
    if not names:
        found = check_injection()
        failures.extend(found)
        if not found:
            counts["sanitizer injections reported at the access"] = 1
    return failures, counts


def main():
    failures, counts = run(sys.argv[1:] or None)
    for failure in failures:
        print(failure)
    for key in sorted(counts):
        print("%s: %d" % (key, counts[key]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
