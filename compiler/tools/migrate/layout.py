"""The two corpora and their files: what is tracked, what is an entry, and how
each entry is compiled."""
import os
import shlex
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SOURCE = "examples"
TARGET = "tests/corpus"


def tracked(prefix=SOURCE, root=REPO):
    """Every tracked file under `prefix`, repository-relative and sorted."""
    r = subprocess.run(["git", "ls-files", "-z", "--", prefix], cwd=root,
                       capture_output=True, check=True)
    return sorted(p for p in r.stdout.decode("utf-8").split("\0") if p)


def header(text):
    """The leading comment block test_runner.py reads its directives from."""
    out = []
    for line in text.split("\n"):
        if line and not line.strip().startswith("//"):
            break
        out.append(line)
    return out


def directive(text):
    """The `// EXPECT:` kind of a test, or None."""
    for line in header(text):
        if "// EXPECT:" in line:
            return line.split("// EXPECT:", 1)[1].strip()
    return None


def is_entry(text):
    kind = directive(text)
    return kind is not None and kind != "skip"


def compile_flags(text, path, root=REPO):
    """The file's `// COMPILE-FLAGS:`, `{TESTDIR}` filled in, minus the
    analysis-only `--emit-*` modes, which stop before place lowering."""
    flags = []
    testdir = os.path.dirname(os.path.join(root, path))
    for line in text.split("\n"):
        if "// COMPILE-FLAGS:" in line:
            raw = line.split("// COMPILE-FLAGS:", 1)[1].strip().replace("{TESTDIR}", testdir)
            flags.extend(shlex.split(raw))
    return [f for f in flags if not f.startswith("--emit-")]


def target_of(path):
    """The migrated twin's path of an `examples/` file."""
    assert path.startswith(SOURCE + "/"), path
    return TARGET + path[len(SOURCE):]


def source_of(path):
    assert path.startswith(TARGET + "/"), path
    return SOURCE + path[len(TARGET):]
