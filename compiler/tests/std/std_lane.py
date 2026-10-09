#!/usr/bin/env python3
"""The std lane: the new std in `std/` under sawc2, the subset checker's std
profile, the lang-item table, and the API equivalence of the two stds.

    python compiler/tests/std/std_lane.py            # check
    python compiler/tests/std/std_lane.py --write    # rewrite the lang dumps and the cones

`compiler/tests/run.py` runs `run()`. It checks:

- every module of the new std resolves, typechecks and lowers to MIR with
  sawc2, with no refusal and no invariant;
- the std profile of compiler/tools/subset_check.py accepts `std/`, and refuses
  each fixture in `subset/` exactly where its `// refuses:` markers say;
- each `lang/` program types the same against `std/` as against `sawc/`: its
  module's typecheck dump is byte-equal under the two roots and to
  `NAME.typecheck`, and its MIR is equal under the two, a refusal's records
  too. `optional_methods` is checked against `std/` alone, and `user_optional`
  is refused as a prelude name while `Optional` stays the prelude's;
- the std prelude's Optional has one `take`, `is_some` and `is_none` each;
- each `shape/NAME.fixture` edit of a copy of `std/` is refused first by the
  rule the fixture names, with its message;
- the API-equivalence of `equivalence.tsv`, under `equivalence_exceptions.tsv`;
- each `pairs/` program exits 0 when Stage 0 builds it against `sawc/std`, and
  checks and lowers clean with sawc2 against `std/`;
- each `cone/` program's new-std cone (compiler/tools/std_cone.py) equals
  `NAME.cone`; `optional_result`'s holds no runtime module, nothing of
  `std.alloc` and no task module, and none holds a task module;
- no fixture here ends a line in whitespace or ends in a blank line.
"""
import collections
import concurrent.futures
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402
import std_cone  # noqa: E402
import subset_check  # noqa: E402

NEW_ROOT = "std"
STAGE0_ROOT = "sawc"
ENTRY = os.path.join(HERE, "entry.saw")
LANG = os.path.join(HERE, "lang")
SHAPE = os.path.join(HERE, "shape")
SUBSET = os.path.join(HERE, "subset")
PAIRS = os.path.join(HERE, "pairs")
CONE = os.path.join(HERE, "cone")
MEMBERS = os.path.join(HERE, "equivalence.tsv")
EXCEPTIONS = os.path.join(HERE, "equivalence_exceptions.tsv")
OUT = os.path.join(REPO, ".build", "std-lane")
TIMEOUT = 300
RUN_TIMEOUT = 60

# The units of SL-456 whose std modules have landed. A member row of a landed
# unit is compared, and an exception due by one fails until it is resolved.
LANDED_UNITS = ("U5b1",)
# The programs of `lang/` checked against the new std only, or refused.
NEW_ONLY = ("optional_methods",)
REFUSED_PAIRED = ("missing_case",)
USER_OPTIONAL = "user_optional"
OPTIONAL_METHODS = ("take", "is_some", "is_none")
# What the cone of a program using only Optional and Result must not reach.
FREESTANDING_CONE = "optional_result"
_MARKER = re.compile(r"//\s*refuses:\s*(.+)$")
_DECLARATION = re.compile(r"^    \((\S+) (\S+) \d+:\d+(.*)\)$")
_CONFORMANCE = re.compile(r"^    \((\S+) (\S+) \d+:\d+(.*)\)$")


def rel(path):
    return os.path.relpath(path, REPO)


def sawc2(*args):
    r = subprocess.run([build.SAWC2] + list(args), cwd=REPO, capture_output=True, text=True,
                       timeout=TIMEOUT)
    return r.returncode, r.stdout


def problems_of(output):
    return [l for l in output.split("\n") if l.startswith(("ERROR\t", "INVARIANT\t"))]


def section(output, name, header="(Module "):
    """The lines of module `name`'s dump section, from its header to the next."""
    out, on = [], False
    for line in output.split("\n"):
        if line.startswith(header):
            on = line == header + name
        if on:
            out.append(line)
    return "\n".join(out).rstrip("\n") + "\n" if out else ""


def module_name(path):
    return os.path.splitext(os.path.basename(path))[0]


# ------------------------------------------------------------- the new std

def check_modules(failures, counts):
    for stage in ("resolve", "typecheck", "mir"):
        _, out = sawc2(stage, "--check", "--std-root", NEW_ROOT, rel(ENTRY))
        for line in problems_of(out):
            failures.append("std %s: %s" % (stage, line))
    counts["std modules"] = len(subset_check.std_tree_files())


def check_profile(failures, counts):
    for d in subset_check.check_std():
        failures.append("std profile: " + d.render())
    fixtures = sorted(glob.glob(os.path.join(SUBSET, "*.saw")))
    for path in fixtures:
        diags = subset_check.check_std([path])
        expected = collections.Counter()
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                m = _MARKER.search(line)
                if m:
                    for name in m.group(1).replace(",", " ").split():
                        expected[(lineno, name)] += 1
        got = collections.Counter((d.line, d.rule) for d in diags)
        for line, name in sorted(set(expected) | set(got)):
            want, have = expected[(line, name)], got[(line, name)]
            if want != have:
                failures.append("std profile fixture %s:%d: expected %s %d time(s), reported %d"
                                % (rel(path), line, name, want, have))
        counts["std profile fixtures"] = counts.get("std profile fixtures", 0) + 1


# ------------------------------------------------------------- the lang items

def check_lang(failures, counts, write):
    for path in sorted(glob.glob(os.path.join(LANG, "*.saw"))):
        name = module_name(path)
        if name == USER_OPTIONAL:
            check_user_optional(failures, path)
            continue
        roots = (NEW_ROOT,) if name in NEW_ONLY else (STAGE0_ROOT, NEW_ROOT)
        dumps, lowered = {}, {}
        for root in roots:
            _, dumps[root] = sawc2("typecheck", "--dump", "--std-root", root, rel(path))
            _, lowered[root] = sawc2("mir", "--dump", "--std-root", root, rel(path))
        if name in REFUSED_PAIRED:
            records = {root: "\n".join(problems_of(dumps[root])) for root in roots}
            if not records[NEW_ROOT]:
                failures.append("std lang %s: nothing refused" % rel(path))
            if records[STAGE0_ROOT] != records[NEW_ROOT]:
                failures.append("std lang %s: the two roots refuse it differently" % rel(path))
            counts["lang cases"] = counts.get("lang cases", 0) + 1
            continue
        for root in roots:
            for line in problems_of(dumps[root]) + problems_of(lowered[root]):
                failures.append("std lang %s (%s): %s" % (rel(path), root, line))
        texts = {root: section(dumps[root], name) for root in roots}
        if len(roots) == 2:
            if texts[STAGE0_ROOT] != texts[NEW_ROOT]:
                failures.append("std lang %s: its typecheck dump differs between %s and %s"
                                % (rel(path), STAGE0_ROOT, NEW_ROOT))
            mirs = {root: section(lowered[root], name, "module ") for root in roots}
            if mirs[STAGE0_ROOT] != mirs[NEW_ROOT]:
                failures.append("std lang %s: its MIR differs between %s and %s"
                                % (rel(path), STAGE0_ROOT, NEW_ROOT))
        expectation = os.path.splitext(path)[0] + ".typecheck"
        if write:
            with open(expectation, "w", encoding="utf-8") as fh:
                fh.write(texts[NEW_ROOT])
        elif not os.path.exists(expectation):
            failures.append("std lang %s: no %s" % (rel(path), rel(expectation)))
        else:
            with open(expectation, encoding="utf-8") as fh:
                if fh.read() != texts[NEW_ROOT]:
                    failures.append("std lang %s: its dump differs from %s"
                                    % (rel(path), rel(expectation)))
        counts["lang cases"] = counts.get("lang cases", 0) + 1
    check_optional_members(failures)


def check_user_optional(failures, path):
    _, out = sawc2("resolve", "--dump", "--std-root", NEW_ROOT, rel(path))
    errors = problems_of(out)
    if not errors or errors[0].split("\t")[1] != "name.reserved":
        failures.append("std lang %s: not refused first as name.reserved" % rel(path))
    if "    (Optional std.prelude.Optional)" not in out.split("\n"):
        failures.append("std lang %s: the Optional role left the std prelude" % rel(path))


def check_optional_members(failures):
    _, out = sawc2("typecheck", "--dump", "--std-root", NEW_ROOT, rel(ENTRY))
    prelude = section(out, "std.prelude").split("\n")
    rows, inside = [], False
    for line in prelude:
        if line == "    (Optional":
            inside = True
        elif inside and line.startswith("      ("):
            rows.append(line.strip("( )").split(" ")[1])
        elif inside:
            break
    for method in OPTIONAL_METHODS:
        if rows.count(method) != 1:
            failures.append("std prelude: Optional's member table holds `%s` %d times, not once"
                            % (method, rows.count(method)))


# ----------------------------------------------------------- shape fixtures

def fixture_fields(path):
    fields = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh.read().split("\n"):
            if line and not line.startswith("//") and ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value
            elif line.endswith(":") and not line.startswith("//"):
                fields[line[:-1]] = ""
    return fields


def fixture_text(value):
    """A fixture's text: as written, or after a leading `|` with each further
    `|` a line break, which keeps leading spaces and empty text writable."""
    if value.startswith("|"):
        return value[1:].replace("|", "\n")
    return value


def check_shapes(failures, counts):
    fixtures = sorted(glob.glob(os.path.join(SHAPE, "*.fixture")))
    for path in fixtures:
        name = os.path.splitext(os.path.basename(path))[0]
        fields = fixture_fields(path)
        root = os.path.join(OUT, "shape", name)
        shutil.rmtree(root, ignore_errors=True)
        shutil.copytree(os.path.join(REPO, NEW_ROOT), root)
        target = os.path.join(root, fields.get("file", ""))
        with open(target, encoding="utf-8") as fh:
            text = fh.read()
        old, new = fixture_text(fields.get("replace", "")), fixture_text(fields.get("with", ""))
        if not old or text.count(old) != 1:
            failures.append("std shape %s: `replace` occurs %d times in %s, not once"
                            % (rel(path), text.count(old) if old else 0, fields.get("file")))
            continue
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new))
        _, out = sawc2("typecheck", "--check", "--std-root", rel(root), rel(ENTRY))
        errors = [l.split("\t") for l in out.split("\n") if l.startswith("ERROR\t")]
        rule, where = (fields.get("refuses", "") + " ").split(" ", 1)
        if not errors:
            failures.append("std shape %s: nothing refused" % rel(path))
            continue
        first = errors[0]
        if first[1] != rule or not os.path.basename(first[2]).startswith(where.strip() + ":"):
            failures.append("std shape %s: refused first as %s at %s, expected %s in %s"
                            % (rel(path), first[1], first[2], rule, where.strip()))
        elif fields.get("message", "") not in first[3]:
            failures.append("std shape %s: the message does not say `%s`: %s"
                            % (rel(path), fields.get("message"), first[3]))
        counts["lang shape fixtures"] = counts.get("lang shape fixtures", 0) + 1


# ------------------------------------------------------------ equivalence

def balanced(text):
    """`text` without the closers of the sections a dump line ends."""
    while text.endswith(")") and text.count(")") > text.count("("):
        text = text[:-1]
    return text


def params_of(rest):
    """A signature record's parameters as `name:Type`, comma-joined, or `-`."""
    at = rest.find("(params")
    if at < 0:
        return "-"
    names, depth, k, start = [], 0, at + len("(params"), None
    while k < len(rest):
        c = rest[k]
        if c == "(":
            depth += 1
            if depth == 1:
                start = k + 1
        elif c == ")":
            if depth == 0:
                break
            if depth == 1 and start is not None:
                words = rest[start:k].split(" ")
                while len(words) > 2 and words[-1] in ("owned", "shared", "exclusive", "default"):
                    words.pop()
                names.append("%s:%s" % (words[0], " ".join(words[1:])))
            depth -= 1
        k += 1
    return ",".join(names) or "-"


def signature_records(output):
    """{declaration key: record}: each declaration and conformance of every
    module, its position and summary left out."""
    out = {}
    module = part = None
    for line in output.split("\n"):
        if line.startswith("(Module "):
            module, part = line[len("(Module "):], None
            continue
        if line.startswith("  (") and module:
            part = line.strip("( ").split(" ")[0]
            continue
        if part == "declarations":
            m = _DECLARATION.match(line)
            if m and m.group(1) != "extension":
                rest = balanced(m.group(3)).split(" (summary ")[0]
                key = "%s %s %s %s" % (module, m.group(1), m.group(2), params_of(rest))
                out[key] = rest
        elif part == "conformances":
            m = _CONFORMANCE.match(line)
            if m:
                owner, trait = m.group(1).split(".")[-1], m.group(2).split(".")[-1]
                out["%s conformance %s %s" % (module, owner, trait)] = balanced(m.group(3))
    return out


def read_rows(path, width):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if line.startswith("#") or not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            rows.append((lineno, fields + [""] * (width - len(fields))))
    return rows


def check_equivalence(failures, counts):
    records = {}
    for root in (STAGE0_ROOT, NEW_ROOT):
        _, out = sawc2("typecheck", "--dump", "--interfaces", "--std-root", root, rel(ENTRY))
        records[root] = signature_records(out)
    _, resolved = sawc2("resolve", "--dump", "--std-root", NEW_ROOT, rel(ENTRY))
    roles = set(re.findall(r"^    \((\w+) [\w.]+\)$", resolved, re.M))
    members = read_rows(MEMBERS, 3)
    exceptions = {fields[0]: (lineno, fields[1], fields[2])
                  for lineno, fields in read_rows(EXCEPTIONS, 3)}
    entries = {fields[0] for _, fields in members}
    for entry in sorted(subset_check.STD_API):
        if entry not in entries:
            failures.append("std equivalence: the allowlist's `%s` has no row in %s"
                            % (entry, rel(MEMBERS)))
    used = set()
    pending = collections.Counter()
    for lineno, (entry, declaration, unit) in members:
        where = "%s:%d" % (rel(MEMBERS), lineno)
        if entry not in subset_check.STD_API and entry != "(api)":
            failures.append("std equivalence %s: `%s` is not on the allowlist" % (where, entry))
        if unit not in LANDED_UNITS:
            pending[unit] += 1
            continue
        if declaration.startswith("lang "):
            if declaration[len("lang "):] not in roles:
                failures.append("std equivalence %s: `%s` is no lang item" % (where, declaration))
            counts["equivalent members"] = counts.get("equivalent members", 0) + 1
            continue
        old = records[STAGE0_ROOT].get(declaration)
        new = records[NEW_ROOT].get(declaration)
        if old is None and new is None:
            failures.append("std equivalence %s: neither std declares `%s`" % (where, declaration))
            continue
        if declaration in exceptions:
            used.add(declaration)
            if old == new:
                failures.append("std equivalence: the exception for `%s` is stale; the two "
                                "stds agree" % declaration)
            continue
        if old != new:
            failures.append("std equivalence %s: `%s` differs: %s has `%s`, %s has `%s`"
                            % (where, declaration, STAGE0_ROOT, old, NEW_ROOT, new))
        counts["equivalent members"] = counts.get("equivalent members", 0) + 1
    for declaration, (lineno, due, reason) in sorted(exceptions.items()):
        where = "%s:%d" % (rel(EXCEPTIONS), lineno)
        if declaration not in used:
            failures.append("std equivalence %s: the exception names no compared member" % where)
        if due in LANDED_UNITS:
            failures.append("std equivalence %s: `%s` was due by %s, which has landed"
                            % (where, declaration, due))
        if not reason:
            failures.append("std equivalence %s: the exception gives no reason" % where)
        if due != "-":
            counts["exceptions due by %s" % due] = counts.get("exceptions due by %s" % due, 0) + 1
    for unit, n in pending.items():
        counts["members pending %s" % unit] = n


# ---------------------------------------------------------------- the pairs

def build_and_run_pair(path):
    exe = os.path.join(OUT, "pairs", module_name(path))
    ok, output = build.build_program(path, exe)
    if not ok:
        return "std pair %s: Stage 0 does not build it: %s" % (rel(path), output.split("\n")[0])
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "std pair %s: timed out under Stage 0" % rel(path)
    if r.returncode != 0:
        return "std pair %s: exit %d under Stage 0: %s" % (rel(path), r.returncode,
                                                           (r.stderr or r.stdout).strip())
    return None


def check_pairs(failures, counts):
    pairs = sorted(glob.glob(os.path.join(PAIRS, "*.saw")))
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as pool:
        for failure in pool.map(build_and_run_pair, pairs):
            if failure:
                failures.append(failure)
    for stage in ("typecheck", "mir"):
        _, out = sawc2(stage, "--check", "--std-root", NEW_ROOT, *[rel(p) for p in pairs])
        for line in problems_of(out):
            failures.append("std pair (%s against %s): %s" % (stage, NEW_ROOT, line))
    counts["behaviour pairs"] = len(pairs)


# ----------------------------------------------------------------- the cones

def check_cones(failures, counts, write):
    for path in sorted(glob.glob(os.path.join(CONE, "*.saw"))):
        name = module_name(path)
        text, problems, _ = std_cone.new_std_cone(path, NEW_ROOT)
        failures += problems
        if text is None:
            continue
        modules = re.findall(r"^(\S+): \d+$", text, re.M)
        for mod in modules:
            if mod.startswith(("rt.", "std.task")):
                failures.append("std cone %s: reaches `%s`" % (rel(path), mod))
        if name == FREESTANDING_CONE:
            if "std.alloc" in modules or "GlobalAllocator" in text:
                failures.append("std cone %s: a program using only Optional and Result "
                                "reaches the allocator" % rel(path))
        expectation = os.path.splitext(path)[0] + ".cone"
        if write:
            with open(expectation, "w", encoding="utf-8") as fh:
                fh.write(text)
        else:
            try:
                with open(expectation, encoding="utf-8") as fh:
                    expected = fh.read()
            except FileNotFoundError:
                expected = ""
            if expected != text:
                added, removed = std_cone.diff_lines(expected, text)
                failures.append("std cone %s: differs from %s; review it and rerun with "
                                "--write" % (rel(path), rel(expectation)))
                failures += ["std cone %s: reached, not listed: %s" % (name, l) for l in added]
                failures += ["std cone %s: listed, not reached: %s" % (name, l) for l in removed]
        counts["std cones"] = counts.get("std cones", 0) + 1


def check_whitespace(failures):
    """No fixture line ends in whitespace and no fixture ends in a blank line,
    which the patch server's `git apply --whitespace=fix` would strip."""
    for path in sorted(glob.glob(os.path.join(HERE, "**", "*.*"), recursive=True)):
        if path.endswith((".py", ".pyc")):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        for lineno, line in enumerate(data.split(b"\n"), 1):
            if line.endswith((b" ", b"\t", b"\r")):
                failures.append("std fixture %s:%d: the line ends in whitespace"
                                % (rel(path), lineno))
        if data.endswith(b"\n\n"):
            failures.append("std fixture %s: ends in a blank line" % rel(path))


def run(write=False):
    failures = []
    counts = {}
    check_whitespace(failures)
    check_modules(failures, counts)
    check_profile(failures, counts)
    check_lang(failures, counts, write)
    check_shapes(failures, counts)
    check_equivalence(failures, counts)
    check_pairs(failures, counts)
    check_cones(failures, counts, write)
    return failures, counts


def main():
    failures, counts = run("--write" in sys.argv[1:])
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("std lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
