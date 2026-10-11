"""The twin the stage1 lane puts where the lanes expect `.build/sawc2`: it runs
the Stage 0-built compiler and the Stage 1 compiler on the same arguments,
hands the lane Stage 0's answer, and appends one record per invocation to the
log: the arguments and whether the two agree on standard output, standard
error and exit status. Configured by STAGE1_REF, STAGE1_NEW and STAGE1_LOG.
"""
import json
import os
import subprocess
import sys


def first_difference(a, b):
    la = a.decode("utf-8", "replace").split("\n")
    lb = b.decode("utf-8", "replace").split("\n")
    for k in range(max(len(la), len(lb))):
        x = la[k] if k < len(la) else "<end>"
        y = lb[k] if k < len(lb) else "<end>"
        if x != y:
            return "line %d: Stage 1 %r, Stage 0 %r" % (k + 1, y[:200], x[:200])
    return ""


def main():
    args = sys.argv[1:]
    ref = subprocess.run([os.environ["STAGE1_REF"]] + args, capture_output=True)
    new = subprocess.run([os.environ["STAGE1_NEW"]] + args, capture_output=True)
    differs = []
    if ref.returncode != new.returncode:
        differs.append("exit %d under Stage 1, %d under Stage 0" % (new.returncode, ref.returncode))
    if ref.stdout != new.stdout:
        differs.append("stdout " + first_difference(ref.stdout, new.stdout))
    if ref.stderr != new.stderr:
        differs.append("stderr " + first_difference(ref.stderr, new.stderr))
    record = {"args": args, "differs": differs}
    line = json.dumps(record, sort_keys=True) + "\n"
    with open(os.environ["STAGE1_LOG"], "a", encoding="utf-8") as fh:
        fh.write(line)
    sys.stdout.buffer.write(ref.stdout)
    sys.stderr.buffer.write(ref.stderr)
    return ref.returncode


if __name__ == "__main__":
    sys.exit(main())
