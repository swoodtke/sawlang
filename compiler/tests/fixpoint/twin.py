"""The twin the fixpoint lane puts where the lanes expect sawc: it runs Stage 1
and Stage 2 on the same arguments, hands the lane Stage 1's answer, and writes
one record per invocation into the log directory: the arguments, the step that
made the call, and whether the two agree on standard output, standard error (a
build's clang temporary object names aside) and exit status. Configured by FIXPOINT_REF (Stage 1), FIXPOINT_NEW (Stage 2) and
FIXPOINT_LOG (the directory). The two stages run at once when the step holds a
second token for the call (SAW_GATE_CALL_TOKENS, compiler/tests/run.py) or one
of the gate's budget is free (`tools/gate_jobs.py`), except for a command that
writes files, whose two runs would write the same paths. A command that
rewrites the files it names in place (`sawc fix`) runs each stage on their
original contents in turn, and the two must also leave the same files. For `sawc lex @LIST`,
which lexes many files in one process, the record names each listed file
whose frame the two stages print differently (`files`), and counts the files.

The twin runs once per sawc call, the recognizer's many small lexes
included, so it imports only what it needs, `gate_jobs` only when it must ask
for a token.
"""
import json
import os
import re
import subprocess
import sys
import threading

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))), "tools")

# The sawc commands that write files at paths their arguments name.
WRITERS = ("build", "runtime")

# The sawc commands that rewrite, in place, the files their arguments name
# (`fix`, unless `--check`): two stages run on one file would each read what the
# other wrote, so each runs on the files' original contents in turn
# (`run_in_place`). The flags that take a value name no such file.
REWRITERS = ("fix",)
VALUE_FLAGS = ("--std-root", "--module-path")

# clang names the object it links through `STEM-XXXXXX.o` with a random
# suffix, and a link failure's message quotes it, so the two stages' stderr
# can differ there and nowhere that means anything (run lane's
# `check_test_only_exports`).
CLANG_TEMP_OBJECT = re.compile(rb"-[0-9a-f]{6}\.o\b")

# `--time-stages` writes each step's wall time, which no two runs share; the
# step names and their order are what the stages must agree on. A step name is
# any text: a split build's `clang unit NAME` names a unit by its module
# (`std.process`) or as `-program`.
STAGE_TIME = re.compile(rb"^(time: [^\n]+ )[0-9]+\.[0-9] ms$", re.MULTILINE)
# The two stages of one split build share the lane's object cache, so the one
# that runs second finds the units the first stored: whether a unit was
# compiled or `cached` is the cache's state, not the stage's.
UNIT_CACHED = re.compile(rb"^(time: clang unit \S+) cached ", re.MULTILINE)
# A warning about the object cache reports its state too: a damaged entry the
# first stage warns about and stores again is whole when the second runs.
CACHE_WARNING = re.compile(rb"^sawc build: warning: [^\n]*object cache[^\n]*\n", re.MULTILINE)


def comparable_stderr(args, err):
    """`err` with clang's temporary object names and `--time-stages`' times
    made equal, for a build, a split build's units compiled or `cached`
    alike, and the object cache's warnings left out."""
    if args[:1] != ["build"]:
        return err
    err = CLANG_TEMP_OBJECT.sub(b"-XXXXXX.o", err)
    err = CACHE_WARNING.sub(b"", err)
    if "--time-stages" in args:
        err = UNIT_CACHED.sub(rb"\1 ", err)
        err = STAGE_TIME.sub(rb"\1N ms", err)
    return err


def first_difference(a, b):
    la = a.decode("utf-8", "replace").split("\n")
    lb = b.decode("utf-8", "replace").split("\n")
    for k in range(max(len(la), len(lb))):
        x = la[k] if k < len(la) else "<end>"
        y = lb[k] if k < len(lb) else "<end>"
        if x != y:
            return "line %d: Stage 2 %r, Stage 1 %r" % (k + 1, y[:200], x[:200])
    return ""


def rewritten_files(args):
    """The files an in-place rewrite's arguments name, each path given or
    listed in an `@LIST`; [] for a command that rewrites none."""
    if args[:1] not in [[c] for c in REWRITERS] or "--check" in args:
        return []
    paths = []
    k = 1
    while k < len(args):
        a = args[k]
        k = k + 1
        if a in VALUE_FLAGS:
            k = k + 1
        elif a.startswith("@"):
            try:
                with open(a[1:], encoding="utf-8") as fh:
                    paths += [line for line in fh.read().split("\n") if line]
            except OSError:
                pass
        elif not a.startswith("-"):
            paths.append(a)
    return paths


def read_or_none(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def put_back(path, data):
    """File `path` holding `data` again, or absent for None."""
    if data is None:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "wb") as fh:
        fh.write(data)


def run_in_place(commands, files):
    """Each stage run on the original contents of `files`, Stage 1 first: the
    originals are kept, Stage 1 runs and what it left is read, the originals
    are put back, and Stage 2 runs, so the files end as Stage 2 left them.
    Returns both answers and, per file, what each stage left."""
    originals = [read_or_none(path) for path in files]
    ref = subprocess.run(commands[0], capture_output=True)
    ref_left = [read_or_none(path) for path in files]
    for path, data in zip(files, originals):
        put_back(path, data)
    new = subprocess.run(commands[1], capture_output=True)
    left = [(path, x, read_or_none(path)) for path, x in zip(files, ref_left)]
    return ref, new, left


def run_both(args):
    """Both stages' answers, and for an in-place rewrite what each left in the
    files it names (`run_in_place`), else []."""
    commands = [[os.environ["FIXPOINT_REF"]] + args, [os.environ["FIXPOINT_NEW"]] + args]
    files = rewritten_files(args)
    if files:
        return run_in_place(commands, files)
    ref, new = run_separately(args, commands)
    return ref, new, []


def run_separately(args, commands):
    """Both stages' answers, at once when a token allows and the command
    writes nothing."""
    if os.environ.get("SAW_GATE_JOBS") == "1" or not args[:1] or args[0] in WRITERS:
        return tuple(subprocess.run(cmd, capture_output=True) for cmd in commands)
    gate_jobs = token = None
    if os.environ.get("SAW_GATE_CALL_TOKENS") != "2":
        sys.path.append(TOOLS)
        import gate_jobs
        token = gate_jobs.try_acquire() if gate_jobs.jobs() >= 2 else None
        if token is None:
            return tuple(subprocess.run(cmd, capture_output=True) for cmd in commands)
    answers = [None, None]

    def run(k):
        answers[k] = subprocess.run(commands[k], capture_output=True)

    try:
        other = threading.Thread(target=run, args=(1,))
        other.start()
        run(0)
        other.join()
        return tuple(answers)
    finally:
        if gate_jobs is not None:
            gate_jobs.release(token)


def listed(args):
    """Whether the call is `sawc lex @LIST`, whose output is one frame per
    listed file, each starting with a `FILE\tPATH` line."""
    return args[:1] == ["lex"] and len(args) == 2 and args[1].startswith("@")


def split_frames(out):
    """[(path, frame bytes)] of a `sawc lex @LIST` output, in order."""
    frames = []
    for line in out.split(b"\n"):
        if line.startswith(b"FILE\t"):
            frames.append([line[5:].decode("utf-8", "replace"), []])
        elif frames:
            frames[-1][1].append(line)
    return [(path, b"\n".join(lines)) for path, lines in frames]


def main():
    args = sys.argv[1:]
    ref, new, left = run_both(args)
    differs = []
    files = []
    for path, x, y in left:
        if x != y:
            difference = first_difference(x or b"<absent>", y or b"<absent>")
            differs.append("the file %s it rewrites %s" % (path, difference))
    if ref.returncode != new.returncode:
        differs.append("exit %d under Stage 2, %d under Stage 1" % (new.returncode, ref.returncode))
    if ref.stdout != new.stdout:
        a, b = split_frames(ref.stdout), split_frames(new.stdout)
        if listed(args) and [p for p, _ in a] == [p for p, _ in b]:
            # Name each listed file the two stages lex differently.
            for (path, x), (_, y) in zip(a, b):
                if x != y:
                    files.append({"path": path, "differs": ["stdout " + first_difference(x, y)]})
        if not files:
            differs.append("stdout " + first_difference(ref.stdout, new.stdout))
    ref_err, new_err = comparable_stderr(args, ref.stderr), comparable_stderr(args, new.stderr)
    if ref_err != new_err:
        differs.append("stderr " + first_difference(ref_err, new_err))
    record = {"args": args, "differs": differs, "files": files, "step": os.environ.get("SAW_GATE_STEP", ""),
              "listed": len(split_frames(ref.stdout)) if listed(args) else 0}
    # The pid and the thread's id are unique among live writers, and O_EXCL
    # refuses a name a finished one already took.
    name = "%d-%d-%d.json" % (os.getpid(), threading.get_ident(), os.times().elapsed * 1e6)
    fd = os.open(os.path.join(os.environ["FIXPOINT_LOG"], name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    sys.stdout.buffer.write(ref.stdout)
    sys.stderr.buffer.write(ref.stderr)
    return ref.returncode


if __name__ == "__main__":
    sys.exit(main())
