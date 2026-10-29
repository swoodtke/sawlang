#!/usr/bin/env python3
"""The typecheck lane: `sawc typecheck` against its golden dumps and refusal fixtures.

    python compiler/tests/typecheck/typecheck_lane.py            # check
    python compiler/tests/typecheck/typecheck_lane.py --write    # rewrite the golden dumps
    python compiler/tests/typecheck/typecheck_lane.py --fill     # fill `// refuses: TODO` headers

`compiler/tests/run.py` runs `run()`. It checks, as README.md in this
directory specifies:

- each golden program, `golden/NAME.saw` or `multi/NAME/main.saw`, checks to
  exactly the record in `golden/NAME.typecheck` or `multi/NAME.typecheck`;
  a first line `// flags: ...` passes those flags, and the record leaves
  out the `std.` modules' dumps;
- each refusal fixture, `refuse/RULE[.VARIANT].saw` or
  `refuse/RULE[.VARIANT]/main.saw`, is refused first by the rule and at the
  position its `// refuses:` header names, checked with the flags a second
  line `// flags: ...` passes (`--runtime`, for a runtime's seams), and that
  refusal's message holds each `// message:` line of its leading comment;
- each warning fixture, `warn/NAME.saw`, draws the `-W borrow-prefix`
  warnings its `// warns: N` header counts, holding each `// message:`
  line, and `sawc fix` rewrites it to `warn/NAME.fixed`, which warns no
  more (`--write` records the `.fixed` files);
- every rule typecheck refuses or warns by has a fixture;
- the compiler's own source, the sawc build and each unit program, checks
  with no refusal;
- no record anywhere carries an `INVARIANT` line from either verifier.
"""
import glob
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402

GOLDEN = os.path.join(HERE, "golden")
MULTI = os.path.join(HERE, "multi")
REFUSE = os.path.join(HERE, "refuse")
WARN = os.path.join(HERE, "warn")
TYPECHECK_SOURCE = os.path.join(COMPILER, "typecheck", "src")
TIMEOUT = 300

_HEADER = re.compile(r"^// refuses: (\S+)(?: at ((?:[\w.-]+\.saw:)?\d+:\d+))?$")
_FLAGS = re.compile(r"^// flags: (.*)$")
_MESSAGE = re.compile(r"^// message: (.+)$")
_WARNS = re.compile(r"^// warns: (\d+)$")
_RULE_ID = re.compile(r'"((?:type|conformance|synthesize|copy|unsafe|slice|member|call|infer|'
                      r'transfer|subscript|pattern|format|extension|implicit-member|operator|'
                      r'init|deinit|effect|match|result|borrowing|borrows|consumes|static|'
                      r'capture|escaping|mutability|nomove|constant|float|static_assert|trait|atomic|lends|'
                      r'export|extern|erasure|spawn|drive|overload|zeroinit|entry|import|alloc|memory|atomics)\.[a-z-]+)"')


def rel(path):
    return os.path.relpath(path, REPO)


def sawc(args):
    r = subprocess.run([build.SAWC, "typecheck"] + with_std_root(args), cwd=REPO, capture_output=True,
                       text=True, timeout=TIMEOUT)
    return r.returncode, r.stdout


def with_std_root(args):
    """`args`, naming the checkout's std when they name no `--std-root`."""
    return list(args) if "--std-root" in args else ["--std-root", "std"] + list(args)


def package_args():
    args = []
    for name, directory in build.STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, directory)]
    return args


def records(output):
    """{path: record text after its FILE line}, in order."""
    out = {}
    current = None
    lines = []
    for line in output.split("\n"):
        if line.startswith("FILE\t"):
            if current is not None:
                out[current] = "\n".join(lines).rstrip("\n") + "\n"
            current = line[len("FILE\t"):]
            lines = []
        else:
            lines.append(line)
    if current is not None:
        out[current] = "\n".join(lines).rstrip("\n") + "\n"
    return out


def golden_cases():
    """(entry path, expectation path), sorted."""
    cases = []
    for src in sorted(glob.glob(os.path.join(GOLDEN, "*.saw"))):
        cases.append((src, os.path.splitext(src)[0] + ".typecheck"))
    for entry in sorted(glob.glob(os.path.join(MULTI, "*", "main.saw"))):
        name = os.path.basename(os.path.dirname(entry))
        cases.append((entry, os.path.join(MULTI, name + ".typecheck")))
    return cases


def refusal_cases():
    cases = sorted(glob.glob(os.path.join(REFUSE, "*.saw")))
    cases += sorted(glob.glob(os.path.join(REFUSE, "*", "main.saw")))
    return cases


def first_difference(expected, got):
    a = expected.split("\n")
    b = got.split("\n")
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else "<end>"
        y = b[i] if i < len(b) else "<end>"
        if x != y:
            return "line %d: expected %r, got %r" % (i + 1, x[:90], y[:90])
    return "a trailing byte"


def golden_flags(src):
    """The flags a golden program's first line `// flags: ...` passes."""
    with open(src) as fh:
        m = _FLAGS.match(fh.readline().rstrip("\n"))
    return tuple(m.group(1).split()) if m else ()


def without_std_modules(record):
    """The record with each `std.` module's dump left out. Std's modules are
    dumped beside the program's, and they are std's lane's to hold. A line
    outside every module, an `ERROR` or `INVARIANT` among them, is kept."""
    out = []
    keep = True
    for line in record.split("\n"):
        if line.startswith("(Module "):
            keep = not line[len("(Module "):].startswith("std.")
        elif line and not line.startswith(" "):
            keep = True
        if keep:
            out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def module_names(record):
    """The names of the modules a dump holds, in order."""
    return [line[len("(Module "):] for line in record.split("\n") if line.startswith("(Module ")]


def check_golden(failures, counts, write):
    groups = {}
    for src, exp in golden_cases():
        groups.setdefault(golden_flags(src), []).append((src, exp))
    for flags, cases in sorted(groups.items()):
        check_golden_group(failures, counts, write, flags, cases)


def check_golden_group(failures, counts, write, flags, cases):
    code, out = sawc(["--dump"] + list(flags) + [rel(src) for src, _ in cases])
    got = {path: without_std_modules(record) for path, record in records(out).items()}
    for src, exp in cases:
        record = got.get(rel(src))
        if record is None:
            failures.append("typecheck golden %s: no record" % rel(src))
            continue
        # The strip must keep the entry's own dump: an empty record would
        # match an empty golden.
        if os.path.splitext(os.path.basename(src))[0] not in module_names(record):
            failures.append("typecheck golden %s: the record holds no dump of its entry module" % rel(src))
            continue
        if write:
            with open(exp, "w") as fh:
                fh.write(record)
            continue
        if not os.path.exists(exp):
            failures.append("typecheck golden %s: no expectation %s" % (rel(src), rel(exp)))
            continue
        with open(exp) as fh:
            expected = fh.read()
        if expected != record:
            failures.append("typecheck golden %s: the record differs at %s"
                            % (rel(src), first_difference(expected, record)))
        counts["typecheck golden cases"] = counts.get("typecheck golden cases", 0) + 1


def header_of(path):
    with open(path) as fh:
        first = fh.readline().rstrip("\n")
    return _HEADER.match(first)


def first_error(record, entry=None):
    """(rule, position) of a record's first refusal, or None. The position is
    `L:C`, after the file's name when that is not the entry's own file."""
    for line in record.split("\n"):
        if line.startswith("ERROR\t"):
            fields = line.split("\t")
            path, row, col = fields[2].rsplit(":", 2)
            if entry is not None and path != entry:
                return fields[1], "%s:%s:%s" % (os.path.basename(path), row, col)
            return fields[1], "%s:%s" % (row, col)
    return None


def first_message(record):
    """The message of a record's first refusal, or ""."""
    for line in record.split("\n"):
        if line.startswith("ERROR\t"):
            return line.split("\t", 3)[3]
    return ""


def fixture_messages(path):
    """The text of each `// message:` line in a fixture's leading comment."""
    messages = []
    with open(path) as fh:
        for line in fh.read().split("\n"):
            if not line.startswith("//"):
                break
            m = _MESSAGE.match(line)
            if m:
                messages.append(m.group(1))
    return messages


def write_header(path, found):
    with open(path) as fh:
        lines = fh.read().split("\n")
    header = "// refuses: NOTHING" if found is None else "// refuses: %s at %s" % found
    if lines and lines[0].startswith("// refuses:"):
        lines[0] = header
    else:
        lines.insert(0, header)
    with open(path, "w") as fh:
        fh.write("\n".join(lines))


def refusal_flags(path):
    """The flags a refusal fixture's second line `// flags: ...` passes."""
    with open(path) as fh:
        fh.readline()
        m = _FLAGS.match(fh.readline().rstrip("\n"))
    return tuple(m.group(1).split()) if m else ()


def check_refusals(failures, counts, fill):
    cases = refusal_cases()
    groups = {}
    for path in cases:
        groups.setdefault(refusal_flags(path), []).append(path)
    got = {}
    for flags, paths in sorted(groups.items()):
        code, out = sawc(["--check"] + list(flags) + [rel(p) for p in paths])
        got.update(records(out))
    named = set()
    for path in cases:
        record = got.get(rel(path), "")
        found = first_error(record, rel(path))
        m = header_of(path)
        if fill and (m is None or m.group(1) == "TODO"):
            write_header(path, found)
            continue
        if m is None:
            failures.append("typecheck refusal %s: no `// refuses: RULE at L:C` header" % rel(path))
            continue
        rule, at = m.group(1), m.group(2)
        named.add(rule)
        if found is None:
            failures.append("typecheck refusal %s: expected %s, nothing refused"
                            % (rel(path), rule))
        elif found[0] != rule:
            failures.append("typecheck refusal %s: expected %s first, refused as %s at %s"
                            % (rel(path), rule, found[0], found[1]))
        elif at and found[1] != at:
            failures.append("typecheck refusal %s: %s at %s, expected at %s"
                            % (rel(path), rule, found[1], at))
        else:
            message = first_message(record)
            for text in fixture_messages(path):
                if text not in message:
                    failures.append("typecheck refusal %s: the message does not hold %r: %s"
                                    % (rel(path), text, message))
        counts["typecheck refusal fixtures"] = counts.get("typecheck refusal fixtures", 0) + 1
    return named


def rule_catalog():
    """Every rule id typecheck's source refuses by."""
    ids = set()
    for path in glob.glob(os.path.join(TYPECHECK_SOURCE, "*.saw")):
        with open(path) as fh:
            ids.update(_RULE_ID.findall(fh.read()))
    return ids


def check_catalog(failures, counts, named):
    catalog = rule_catalog()
    for rule in sorted(catalog):
        if rule not in named:
            failures.append("typecheck rule %s has no refusal fixture" % rule)
    for rule in sorted(named):
        if rule not in catalog:
            failures.append("typecheck fixtures name %s, which typecheck does not refuse by"
                            % rule)
    counts["typecheck rules"] = len(catalog)


def unit_programs():
    return sorted(glob.glob(os.path.join(COMPILER, "*", "tests", "*.saw")))


def check_acceptance(failures, counts, nonsync=None):
    """The compiler's own source checks whole: the sawc build, then each unit
    program, each the entry of its own program. A unit program the parser
    refuses has no tree to check and is counted apart. The subset is
    sync-only, so no function in compiler/ may suspend; how many are
    sync-callable is information, and `nonsync` collects those that are not.
    A std function the sawc build calls and the suspension table has no row
    for fails too."""
    entries = [rel(build.DRIVER_ENTRY)] + [rel(p) for p in unit_programs()]
    code, out = sawc(["--check", "--notes", "--summaries", "--std-root", "std"] + package_args() + entries)
    got = records(out)
    # Only the compiler's own functions are held to sync-only: the new std is
    # compiled whole and suspends where it should. An entry's module is named
    # by its file, not by a stage package, so its name is listed too.
    own = {name for name, _ in build.STAGE_PACKAGES}
    own |= {os.path.splitext(os.path.basename(entry))[0] for entry in entries}
    summarized = {}
    for entry in entries:
        record = got.get(entry)
        if record is None:
            failures.append("typecheck acceptance %s: no record" % entry)
            continue
        lines = [l for l in record.split("\n") if l.startswith(("ERROR\t", "INVARIANT\t"))]
        if lines and all("\tresolve.parse-refused\t" in l for l in lines) and entry != entries[0]:
            counts["unit programs the parser refuses"] = (
                counts.get("unit programs the parser refuses", 0) + 1)
            continue
        for line in lines:
            failures.append("typecheck acceptance %s: %s" % (entry, line))
        for line in record.split("\n"):
            if line.startswith("NOTE\tsummary.untabled\t"):
                failures.append("typecheck acceptance %s: %s" % (entry, line))
            if line.startswith("SUMMARY\t"):
                _, identity, suspends, sync = line.split("\t")
                if identity.split(".")[0] in own:
                    summarized[identity] = (suspends, sync)
        counts["checked compiler programs"] = counts.get("checked compiler programs", 0) + 1
    for identity in sorted(summarized):
        suspends, sync = summarized[identity]
        if suspends != "never-suspends":
            failures.append("typecheck acceptance: %s may suspend (%s), and the subset is sync-only"
                            % (identity, suspends))
        if sync == "sync-callable":
            counts["compiler functions sync-callable"] = (
                counts.get("compiler functions sync-callable", 0) + 1)
        elif nonsync is not None:
            nonsync.append("%s (%s)" % (identity, sync))
    counts["compiler functions summarized"] = len(summarized)


def check_invariants(failures, output_records):
    for path, record in output_records.items():
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("typecheck %s: %s" % (path, line))


def warning_cases():
    return sorted(glob.glob(os.path.join(WARN, "*.saw")))


def warning_lines(path):
    """The WARNING lines `sawc typecheck -W borrow-prefix` prints for `path`."""
    code, out = sawc(["--check", "-W", "borrow-prefix", path])
    return [l for l in out.split("\n") if l.startswith("WARNING\t")]


def check_warnings(failures, counts, write):
    """Each `warn/NAME.saw` draws the warnings its `// warns: N` header
    counts, each `// message:` text among them, and `sawc fix` rewrites it
    to `warn/NAME.fixed` exactly, which draws none (the fix is idempotent).
    `--write` records the `.fixed` files."""
    named = set()
    for path in warning_cases():
        with open(path) as fh:
            text = fh.read()
        m = _WARNS.match(text.split("\n", 1)[0])
        if m is None:
            failures.append("typecheck warning %s: no `// warns: N` header" % rel(path))
            continue
        lines = warning_lines(rel(path))
        for line in lines:
            named.add(line.split("\t")[1])
        if len(lines) != int(m.group(1)):
            failures.append("typecheck warning %s: %d warnings, expected %s: %s"
                            % (rel(path), len(lines), m.group(1), lines[:3]))
        for want in fixture_messages(path):
            if not any(want in line for line in lines):
                failures.append("typecheck warning %s: no warning holds %r" % (rel(path), want))
        with tempfile.TemporaryDirectory() as scratch:
            copy = os.path.join(scratch, os.path.basename(path))
            with open(copy, "w") as fh:
                fh.write(text)
            r = subprocess.run([build.SAWC, "fix"] + with_std_root([copy]), cwd=REPO, capture_output=True,
                               text=True, timeout=TIMEOUT)
            with open(copy) as fh:
                fixed = fh.read()
            if r.returncode != 0:
                failures.append("typecheck warning %s: `sawc fix` exited %d: %s"
                                % (rel(path), r.returncode, r.stdout[-300:]))
            again = warning_lines(copy)
            if again:
                failures.append("typecheck warning %s: the fixed file still warns: %s" % (rel(path), again[:2]))
        expected = os.path.splitext(path)[0] + ".fixed"
        if write:
            with open(expected, "w") as fh:
                fh.write(fixed)
        elif not os.path.exists(expected):
            failures.append("typecheck warning %s: no %s" % (rel(path), rel(expected)))
        else:
            with open(expected) as fh:
                want = fh.read()
            if want != fixed:
                failures.append("typecheck warning %s: `sawc fix` gives otherwise than %s: %s"
                                % (rel(path), rel(expected), first_difference(want, fixed)))
        counts["typecheck warning fixtures"] = counts.get("typecheck warning fixtures", 0) + 1
    return named


def run(write=False, fill=False, nonsync=None):
    failures = []
    counts = {}
    check_golden(failures, counts, write)
    named = check_refusals(failures, counts, fill)
    named |= check_warnings(failures, counts, write)
    code, out = sawc(["--check"] + [rel(p) for p in refusal_cases()]
                      + [rel(src) for src, _ in golden_cases()])
    check_invariants(failures, records(out))
    check_catalog(failures, counts, named)
    check_acceptance(failures, counts, nonsync)
    return failures, counts


def main():
    write = "--write" in sys.argv[1:]
    fill = "--fill" in sys.argv[1:]
    nonsync = []
    failures, counts = run(write, fill, nonsync)
    for name in nonsync:
        print("not sync-callable: %s" % name)
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("typecheck lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
