#!/usr/bin/env python3
"""The std lane: the new std in `std/` under sawc2, the subset checker's std
profile, the lang-item table, and the API equivalence of the two stds.

    python compiler/tests/std/std_lane.py            # check
    python compiler/tests/std/std_lane.py --write    # rewrite the lang dumps and the cones

`compiler/tests/run.py` runs `run()`. It checks:

- every module of the new std resolves, typechecks, lowers to MIR and has its
  constants evaluated with sawc2, with no refusal and no invariant;
- the std profile of compiler/tools/subset_check.py accepts `std/`, and refuses
  each fixture in `subset/` exactly where its `// refuses:` markers say;
- each `lang/` program types the same against `std/` as against `sawc/`: its
  module's typecheck dump is byte-equal under the two roots, but for the
  new std's `(string-positions ...)` section, and to `NAME.typecheck`, and its
  MIR is equal under the two, a refusal's records too. `optional_methods` and
  `string_positions` are checked against `std/` alone, and `user_optional` is
  refused as a prelude name while `Optional` stays the prelude's;
- the std prelude's Optional has one `take`, `is_some` and `is_none` each;
- each `shape/NAME.fixture` edit of a copy of `std/` is refused first by the
  rule the fixture names, with its message;
- the API-equivalence of `equivalence.tsv`, under `equivalence_exceptions.tsv`:
  signature records, String's layout, and the conformance sets of String and
  Vector, read off which trait bounds each type meets under each root;
- each `pairs/` program exits 0 when Stage 0 builds it against `sawc/std`, or
  panics with the text its `// expect-panic:` line names, and checks, lowers
  and evaluates clean with sawc2 against `std/`;
- each `calls/` program, which only the new std's API can type, checks clean
  through drop elaboration against `std/`, or, headed `// refuses: RULE at
  L:C`, is refused first there by that rule;
- each `mir/NAME.mir` holds its functions' MIR as sawc2 lowers them against
  `std/`, and String's retain and release read the count with a relaxed
  atomic load and compare it with the immortal sentinel before any atomic
  read-modify-write;
- each `cone/` program's new-std cone (compiler/tools/std_cone.py) equals
  `NAME.cone`; `optional_result`'s and `literal_only`'s hold no runtime module,
  nothing of `std.alloc` and no task module, `interpolation`'s reaches the
  builder and the allocator, and none holds a task module;
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
CALLS = os.path.join(HERE, "calls")
CONE = os.path.join(HERE, "cone")
MIR = os.path.join(HERE, "mir")
MEMBERS = os.path.join(HERE, "equivalence.tsv")
EXCEPTIONS = os.path.join(HERE, "equivalence_exceptions.tsv")
OUT = os.path.join(REPO, ".build", "std-lane")
TIMEOUT = 300
RUN_TIMEOUT = 60

# The units of SL-456 whose std modules have landed. A member row of a landed
# unit is compared, and an exception due by one fails until it is resolved.
LANDED_UNITS = ("U5b1", "U5b2")
# The programs of `lang/` checked against the new std only, or refused.
NEW_ONLY = ("optional_methods", "string_positions")
REFUSED_PAIRED = ("missing_case",)
USER_OPTIONAL = "user_optional"
OPTIONAL_METHODS = ("take", "is_some", "is_none")
# The cones that must reach no allocator: a program using only Optional and
# Result, and one whose only Strings are literals.
NO_ALLOCATOR_CONES = ("optional_result", "literal_only")
# The cone of a program that interpolates, which reaches the builder and the
# allocator.
BUILDER_CONE = "interpolation"
# The conformance probe: the traits whose bounds each type's set is read off,
# and an expression of the type for the probe to pass.
PROBE_TRAITS = ("Copy", "ExplicitCopy", "NoCopy", "Equatable", "Comparable", "Hashable",
                "Printable", "Error", "Send", "Sync")
PROBE_VALUES = {"String": "\"probe\"", "Vector": "Vector<Int>()"}
# String's layout under the new std: its declaration's fields, which the
# `string_layout` pair holds to Stage 0's size and alignment.
LAYOUT_FIELDS = {"String": {"std.string field String.bytes -": " private UnsafePointer<Int8>"}}
LAYOUT_PAIR = "string_layout"
# The functions each `mir/` pin holds, and String's refcount hooks, which read
# the count with a relaxed atomic load and compare it with the immortal
# sentinel before any atomic read-modify-write (SL:open-questions D24).
REFCOUNT_HOOKS = ("fn std.string.String.copy()", "fn std.string.String.deinit()")
SENTINEL = "static std.string.IMMORTAL"
RELAXED_LOAD = "call builtin __saw_atomic_load_i64_relaxed"
ATOMIC_RMW = ("call builtin __saw_atomic_add_i64", "call builtin __saw_atomic_sub_i64_release")
_MARKER = re.compile(r"//\s*refuses:\s*(.+)$")
_EXPECT_PANIC = re.compile(r"^//\s*expect-panic:\s*(.+)$")
_REFUSES = re.compile(r"^// refuses: (\S+) at (\d+:\d+)$")
_PIN_FUNCTION = re.compile(r"^// function: (.+)$")
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


def without_string_positions(text):
    """A new-std module dump without its `(string-positions ...)` section,
    which only the new std's dump prints: under Stage 0's std the String
    positions lower through what its compiler synthesizes."""
    out, inside = [], False
    for line in text.split("\n"):
        if line == "  (string-positions":
            inside = True
            out[-1] = out[-1] + ")"
            continue
        if inside:
            if not line.startswith("    "):
                inside = False
            else:
                continue
        out.append(line)
    return "\n".join(out)


def module_name(path):
    return os.path.splitext(os.path.basename(path))[0]


# ------------------------------------------------------------- the new std

def check_modules(failures, counts):
    for stage in ("resolve", "typecheck", "mir", "eval"):
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
            if texts[STAGE0_ROOT] != without_string_positions(texts[NEW_ROOT]):
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
    probed = []
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
        if declaration.startswith("layout "):
            check_layout(failures, where, declaration[len("layout "):], records[NEW_ROOT])
            counts["equivalent layouts"] = counts.get("equivalent layouts", 0) + 1
            continue
        if declaration.startswith("conformances "):
            probed.append((where, declaration[len("conformances "):]))
            continue
        if declaration.startswith("paired "):
            name = declaration[len("paired "):]
            if name in NEW_ONLY or not os.path.exists(os.path.join(LANG, name + ".saw")):
                failures.append("std equivalence %s: no paired program lang/%s.saw" % (where, name))
            counts["equivalent members"] = counts.get("equivalent members", 0) + 1
            continue
        old = records[STAGE0_ROOT].get(stage0_key(declaration))
        new = records[NEW_ROOT].get(new_key(declaration))
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
    if probed:
        sets = conformance_sets([name for _, name in probed], failures)
        for where, name in probed:
            old, new = sets.get((STAGE0_ROOT, name)), sets.get((NEW_ROOT, name))
            if old != new:
                failures.append("std equivalence %s: %s's conformances differ: %s meets %s, %s meets %s"
                                % (where, name, STAGE0_ROOT, sorted(old or ()), NEW_ROOT,
                                   sorted(new or ())))
            counts["equivalent conformance sets"] = counts.get("equivalent conformance sets", 0) + 1


# A member row may name the vocabulary module, which is `builtin` under Stage
# 0's std and the prelude under the new one.
def stage0_key(declaration):
    if declaration.startswith("vocabulary "):
        return "builtin " + declaration[len("vocabulary "):]
    return declaration


def new_key(declaration):
    if declaration.startswith("vocabulary "):
        return "std.prelude " + declaration[len("vocabulary "):]
    return declaration


def check_layout(failures, where, name, records):
    """The new std's declaration of `name` holds exactly the fields
    LAYOUT_FIELDS names, and the pair that holds Stage 0's size to them runs."""
    prefix = "std.string field %s." % name
    found = {key: rest for key, rest in records.items() if key.startswith(prefix)}
    if found != LAYOUT_FIELDS.get(name):
        failures.append("std equivalence %s: %s's fields are %s, not one pointer: %s"
                        % (where, name, sorted(found.items()), LAYOUT_FIELDS.get(name)))
    if not os.path.exists(os.path.join(PAIRS, LAYOUT_PAIR + ".saw")):
        failures.append("std equivalence %s: no pair pairs/%s.saw holds %s's size to Stage 0's"
                        % (where, LAYOUT_PAIR, name))


def conformance_sets(names, failures):
    """{(root, type): the PROBE_TRAITS whose bound a value of the type meets},
    each trait one probe program, all of a root's probes in one sawc2 run."""
    probe_dir = os.path.join(OUT, "probe")
    shutil.rmtree(probe_dir, ignore_errors=True)
    os.makedirs(probe_dir)
    paths = {}
    for name in names:
        for trait in PROBE_TRAITS:
            path = os.path.join(probe_dir, "%s_%s.saw" % (name.lower(), trait.lower()))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("func probe<T: %s>(value: &T) -> Int {\n    0\n}\n\n"
                         "func main() -> Int {\n    let value = %s\n    probe(&value)\n}\n"
                         % (trait, PROBE_VALUES[name]))
            paths[rel(path)] = (name, trait)
    sets = {}
    for root in (STAGE0_ROOT, NEW_ROOT):
        _, out = sawc2("typecheck", "--check", "--std-root", root, *sorted(paths))
        refused, current = set(), None
        for line in out.split("\n"):
            if line.startswith("FILE\t"):
                current = line.split("\t", 1)[1]
            elif line.startswith("INVARIANT\t"):
                failures.append("std conformance probe %s (%s): %s" % (current, root, line))
            elif line.startswith("ERROR\t") and current is not None:
                refused.add(current)
        for path, (name, trait) in paths.items():
            if path not in refused:
                sets.setdefault((root, name), set()).add(trait)
            sets.setdefault((root, name), set())
    return sets


# ---------------------------------------------------------------- the pairs

def expected_panic(path):
    """The text a pair's `// expect-panic:` first line says its panic prints,
    or None for a pair that exits 0."""
    with open(path, encoding="utf-8") as fh:
        m = _EXPECT_PANIC.match(fh.readline().rstrip("\n"))
    return m.group(1) if m else None


def build_and_run_pair(path):
    exe = os.path.join(OUT, "pairs", module_name(path))
    ok, output = build.build_program(path, exe)
    if not ok:
        return "std pair %s: Stage 0 does not build it: %s" % (rel(path), output.split("\n")[0])
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "std pair %s: timed out under Stage 0" % rel(path)
    panic = expected_panic(path)
    said = (r.stderr + r.stdout).strip()
    if panic is not None:
        if r.returncode == 0 or panic not in said:
            return "std pair %s: expected a panic saying `%s` under Stage 0, got exit %d: %s" \
                % (rel(path), panic, r.returncode, said)
        return None
    if r.returncode != 0:
        return "std pair %s: exit %d under Stage 0: %s" % (rel(path), r.returncode, said)
    return None


def check_pairs(failures, counts):
    pairs = sorted(glob.glob(os.path.join(PAIRS, "*.saw")))
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as pool:
        for failure in pool.map(build_and_run_pair, pairs):
            if failure:
                failures.append(failure)
    for stage in ("typecheck", "mir", "eval"):
        _, out = sawc2(stage, "--check", "--std-root", NEW_ROOT, *[rel(p) for p in pairs])
        for line in problems_of(out):
            failures.append("std pair (%s against %s): %s" % (stage, NEW_ROOT, line))
    counts["behaviour pairs"] = len(pairs)


# ------------------------------------------------------------ the call programs

def file_sections(output):
    """{file: its problem lines}, from a `--check` run over several files."""
    out, current = {}, None
    for line in output.split("\n"):
        if line.startswith("FILE\t"):
            current = line[len("FILE\t"):]
            out[current] = []
        elif current is not None and line.startswith(("ERROR\t", "INVARIANT\t")):
            out[current].append(line)
    return out


def check_calls(failures, counts):
    """Each `calls/` program against the new std alone, where Stage 0's std
    cannot say it: one headed `// refuses: RULE at L:C` is refused first there,
    by that rule, and any other checks clean through drop elaboration."""
    programs = sorted(glob.glob(os.path.join(CALLS, "*.saw")))
    headers = {}
    for path in programs:
        with open(path, encoding="utf-8") as fh:
            headers[rel(path)] = _REFUSES.match(fh.readline().rstrip("\n"))
    _, typed = sawc2("typecheck", "--check", "--std-root", NEW_ROOT, *sorted(headers))
    _, dropped = sawc2("drops", "--check", "--std-root", NEW_ROOT, *sorted(headers))
    typed, dropped = file_sections(typed), file_sections(dropped)
    for path, m in sorted(headers.items()):
        if m is None:
            for line in dropped.get(path, ["(no record)"]):
                failures.append("std call %s: %s" % (path, line))
            counts["std call programs"] = counts.get("std call programs", 0) + 1
            continue
        errors = [l.split("\t") for l in typed.get(path, []) if l.startswith("ERROR\t")]
        if not errors:
            failures.append("std call %s: expected %s, nothing refused" % (path, m.group(1)))
        elif errors[0][1] != m.group(1) or not errors[0][2].endswith(":" + m.group(2)):
            failures.append("std call %s: expected %s at %s first, refused as %s at %s"
                            % (path, m.group(1), m.group(2), errors[0][1], errors[0][2]))
        counts["std call refusals"] = counts.get("std call refusals", 0) + 1


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
        if name in NO_ALLOCATOR_CONES:
            if "std.alloc" in modules or "GlobalAllocator" in text:
                failures.append("std cone %s: reaches the allocator, which this program "
                                "must not" % rel(path))
        if name == BUILDER_CONE:
            for wanted in ("std.stringbuilder", "std.alloc"):
                if wanted not in modules:
                    failures.append("std cone %s: an interpolation does not reach `%s`"
                                    % (rel(path), wanted))
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


# ------------------------------------------------------------- the MIR pins

def mir_functions(dump):
    """{header line: the function's text}, each function of a MIR dump from its
    `fn` line through its closing brace."""
    out, current, lines = {}, None, []
    for line in dump.split("\n"):
        if line.startswith("fn "):
            current, lines = line, [line]
        elif current is not None:
            lines.append(line)
            if line == "}":
                out[current] = "\n".join(lines) + "\n"
                current = None
    return out


def pin_parts(path):
    """A pin's header comments, the functions it names, and its text after the
    header."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    header, names = [], []
    rest = text.split("\n")
    while rest and rest[0].startswith("//"):
        line = rest.pop(0)
        header.append(line)
        m = _PIN_FUNCTION.match(line)
        if m:
            names.append(m.group(1))
    return header, names, "\n".join(rest)


def pinned_text(functions, names):
    parts = []
    for name in names:
        found = [text for header, text in functions.items() if header.startswith(name + " ")]
        parts.append(found[0] if len(found) == 1 else "(no single function `%s`)\n" % name)
    return "\n".join(parts)


_BLOCK = re.compile(r"^    (bb\d+): \{$", re.M)
_RETURN_TO = re.compile(r"-> \[return: (bb\d+)\]")


def refcount_order_problem(body):
    """Why a refcount hook's MIR may write before it knows the block is not
    immortal, or None. The entry block must end in the relaxed load and hold
    no read-modify-write, and the block the load returns to must compare the
    count with the sentinel: then every read-modify-write lies past both."""
    blocks = {}
    marks = list(_BLOCK.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        blocks[m.group(1)] = body[m.end():end]
    entry = blocks.get("bb0", "")
    if any(op in entry for op in ATOMIC_RMW):
        return "performs an atomic read-modify-write in its entry block"
    if RELAXED_LOAD not in entry:
        return ("does not read the count with a relaxed atomic load in its entry block "
                "(SL:open-questions D24)")
    after = _RETURN_TO.search(entry[entry.find(RELAXED_LOAD):])
    if after is None or SENTINEL not in blocks.get(after.group(1), ""):
        return "does not compare the loaded count with the immortal sentinel next"
    if not any(op in body for op in ATOMIC_RMW):
        return "performs no atomic read-modify-write at all"
    return None


def check_mir_pins(failures, counts, write):
    _, dump = sawc2("mir", "--dump", "--std-root", NEW_ROOT, rel(ENTRY))
    functions = mir_functions(dump)
    for header in REFCOUNT_HOOKS:
        found = [text for line, text in functions.items() if line.startswith(header + " ")]
        if len(found) != 1:
            failures.append("std mir: no single `%s` in the new std's MIR" % header)
            continue
        problem = refcount_order_problem(found[0])
        if problem:
            failures.append("std mir: `%s` %s, so a literal's block could be written"
                            % (header, problem))
    for path in sorted(glob.glob(os.path.join(MIR, "*.mir"))):
        header, names, expected = pin_parts(path)
        got = pinned_text(functions, names)
        if write:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(header) + "\n" + got)
        elif got != expected:
            failures.append("std mir %s: the pinned functions' MIR differs; review it and rerun "
                            "with --write" % rel(path))
        counts["std mir pins"] = counts.get("std mir pins", 0) + 1


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
    check_calls(failures, counts)
    check_mir_pins(failures, counts, write)
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
