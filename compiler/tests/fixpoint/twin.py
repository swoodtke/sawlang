"""The twin the fixpoint lane puts where the lanes expect sawc2: it runs Stage 1
and Stage 2 on the same arguments, hands the lane Stage 1's answer, and writes
one record per invocation into the log directory: the arguments, the step that
made the call, and whether the two agree on standard output, standard error and
exit status. Configured by FIXPOINT_REF (Stage 1), FIXPOINT_NEW (Stage 2) and
FIXPOINT_LOG (the directory). The two stages run at once when the step holds a
second token for the call (SAW_GATE_CALL_TOKENS, compiler/tests/run.py) or one
of the gate's budget is free (`tools/gate_jobs.py`), except for a command that
writes files, whose two runs would write the same paths.
"""
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))), "tools"))

import gate_jobs  # noqa: E402

# The sawc2 commands that write files at paths their arguments name.
WRITERS = ("build", "runtime")


def first_difference(a, b):
    la = a.decode("utf-8", "replace").split("\n")
    lb = b.decode("utf-8", "replace").split("\n")
    for k in range(max(len(la), len(lb))):
        x = la[k] if k < len(la) else "<end>"
        y = lb[k] if k < len(lb) else "<end>"
        if x != y:
            return "line %d: Stage 2 %r, Stage 1 %r" % (k + 1, y[:200], x[:200])
    return ""


def run_both(args):
    commands = [[os.environ["FIXPOINT_REF"]] + args, [os.environ["FIXPOINT_NEW"]] + args]
    together = False
    token = None
    if gate_jobs.jobs() >= 2 and args[:1] and args[0] not in WRITERS:
        together = os.environ.get("SAW_GATE_CALL_TOKENS") == "2"
        if not together:
            token = gate_jobs.try_acquire()
            together = token is not None
    if not together:
        return tuple(subprocess.run(cmd, capture_output=True) for cmd in commands)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            ref, new = pool.map(lambda cmd: subprocess.run(cmd, capture_output=True), commands)
        return ref, new
    finally:
        gate_jobs.release(token)


def main():
    args = sys.argv[1:]
    ref, new = run_both(args)
    differs = []
    if ref.returncode != new.returncode:
        differs.append("exit %d under Stage 2, %d under Stage 1" % (new.returncode, ref.returncode))
    if ref.stdout != new.stdout:
        differs.append("stdout " + first_difference(ref.stdout, new.stdout))
    if ref.stderr != new.stderr:
        differs.append("stderr " + first_difference(ref.stderr, new.stderr))
    record = {"args": args, "differs": differs, "step": os.environ.get("SAW_GATE_STEP", "")}
    fd, path = tempfile.mkstemp(suffix=".json", dir=os.environ["FIXPOINT_LOG"])
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    sys.stdout.buffer.write(ref.stdout)
    sys.stderr.buffer.write(ref.stderr)
    return ref.returncode


if __name__ == "__main__":
    sys.exit(main())
