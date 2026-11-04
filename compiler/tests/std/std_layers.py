"""Std's layer of the front end is the same in every program (SL-955 unit 4).

    python compiler/tests/std/std_layers.py

The front end runs std's layer through drop elaboration before it loads the
program's first module, so std's state at that cut depends on std, the target,
the profile and the compiler alone. Over the programs below, which reach into
std's tables from their own layer in different ways, this checks that each sees
the same std:

- the cut's id-level counts: the program layer's watermarks, which
  `sawc drops --dump` prints in the `std.prelude` section's `layers` block, the
  length of every program-wide table at the cut (modules, declarations, nodes,
  imports, conformances, interned names, types, MIR functions, statements and
  places among them);
- each std module's drop-elaborated MIR (`sawc drops --dump`);
- std's summaries (`sawc typecheck --summaries`);
- each std module's typecheck dump, without its `(views` block, which is std's
  view of the program's own types, and without the member rows a non-std
  module's extension or conformance brings to a std type's table: the program
  layer rebuilds such a table at the end of the member arena, and the dump
  prints the table it ends with.

and, at the id level, std's front-end image (compiler/mono/src/frontimage.saw):
the whole state at the cut, every arena and side table no dump prints
included, encoded as each program's build makes it, must be the same bytes
for these programs and for sawc itself. `compiler/mono/tests/front_image.saw`
writes the image (`--std-image`).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))
sys.path.append(os.path.join(REPO, "tools"))

import blade_lane  # noqa: E402
import build  # noqa: E402

TIMEOUT = 300
LAYERS = os.path.join(HERE, "layers")
IMAGE_TOOL = os.path.join(COMPILER, "mono", "tests", "front_image.saw")
IMAGE_OUT = os.path.join(REPO, ".build", "std-layers")


def blade_flags():
    flags = []
    for name, directory in blade_lane.MODULE_PATHS:
        flags += ["--module-path", "%s=%s" % (name, os.path.relpath(directory, REPO))]
    return flags


# The first is the reference: a program with nothing of its own.
PROGRAMS = (
    ("empty", os.path.join(LAYERS, "empty.saw"), ()),
    ("hello", os.path.join(TESTS, "run", "hello.saw"), ()),
    ("ext_probe", os.path.join(LAYERS, "ext_probe.saw"), ()),
    ("blade", os.path.join(blade_lane.BLADE_DIR, "src", "main.saw"), "blade"),
)

# The image check also covers sawc, whose dumps are too large to compare here.
IMAGE_PROGRAMS = PROGRAMS + (
    ("sawc", os.path.join(COMPILER, "driver", "src", "main.saw"), "sawc"),
)


def mappings(flags):
    """A program's `--module-path` mappings as NAME=DIR, repository-relative."""
    if flags == "blade":
        pairs = blade_lane.MODULE_PATHS
    elif flags == "sawc":
        pairs = [(name, os.path.join(REPO, path)) for name, path in build.STAGE_PACKAGES]
    else:
        pairs = []
    return ["%s=%s" % (name, os.path.relpath(directory, REPO)) for name, directory in pairs]


def check_images():
    """Failures, and how many programs' std images were compared."""
    os.makedirs(IMAGE_OUT, exist_ok=True)
    tool = os.path.join(IMAGE_OUT, "front_image")
    ok, output = build.build_program(IMAGE_TOOL, tool)
    if not ok:
        return ["std layers: the image tool does not build: %s" % output.strip().split("\n")[0]], 0
    images = {}
    failures = []
    for name, path, flags in IMAGE_PROGRAMS:
        out = os.path.join(IMAGE_OUT, "%s.img" % name)
        r = subprocess.run([tool, "--std-image", out, rel(path)] + mappings(flags), cwd=REPO,
                           capture_output=True, text=True, timeout=TIMEOUT)
        if r.returncode != 0:
            failures.append("std layers %s: the image tool exits %d: %s"
                            % (name, r.returncode, (r.stdout + r.stderr).strip()[:200]))
            continue
        with open(out, "rb") as fh:
            images[name] = fh.read()
    reference = IMAGE_PROGRAMS[0][0]
    if reference in images:
        for name, data in images.items():
            if data != images[reference]:
                at = next((k for k in range(min(len(data), len(images[reference])))
                           if data[k] != images[reference][k]), min(len(data), len(images[reference])))
                failures.append("std layers %s: std's image differs from %s's, first at byte %d (%d bytes "
                                "against %d)" % (name, reference, at, len(data), len(images[reference])))
    return failures, len(images)

_ROW_FROM = re.compile(r"\((extension|default|synthesized) ([A-Za-z_][A-Za-z0-9_.]*)\)")


def rel(path):
    return os.path.relpath(path, REPO)


def sawc(*args):
    r = subprocess.run([build.SAWC] + list(args), cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    return r.returncode, r.stdout


def sections(text, header):
    """{module: its section's lines}, a section running from its header line
    to the next."""
    out, current = {}, None
    for line in text.split("\n"):
        name = header(line)
        if name is not None:
            current = name
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return out


def drops_header(line):
    return line[len("module "):] if line.startswith("module ") else None


def typecheck_header(line):
    return line.split()[1].strip("()") if line.startswith("(Module ") else None


def is_std(module):
    return module == "std" or module.startswith("std.")


def program_row(line):
    """Whether a member-table row is one a non-std module brings: an extension
    of that module, or the default or derivation of a trait it declares, which
    prints qualified by its module (a std trait in the prelude prints bare)."""
    m = _ROW_FROM.search(line)
    if m is None:
        return False
    if m.group(1) == "extension":
        return not is_std(m.group(2))
    return "." in m.group(2) and not is_std(m.group(2))


def std_typecheck(lines):
    """A std module's typecheck section without its `(views` block and the
    member rows another layer brings; trailing parentheses are dropped from
    each line, since dropping a row moves the one that closes a table."""
    out, skipping = [], False
    for line in lines:
        if line.startswith("  (views"):
            skipping = True
            continue
        if skipping and line.startswith("    "):
            continue
        skipping = False
        if program_row(line):
            continue
        out.append(line.rstrip(")"))
    return out


def cut_line(lines):
    """The program layer's watermarks from the `std.prelude` drops section."""
    for line in lines:
        if line.startswith("  program "):
            return line.strip()
    return None


def views(name, path, flags):
    """What the checks compare for one program, or a failure."""
    extra = blade_flags() if flags == "blade" else list(flags)
    code, dropped = sawc("drops", "--dump", "--std-root", "std", *extra, rel(path))
    if code != 0:
        return None, "std layers %s: `sawc drops` exits %d" % (name, code)
    code, checked = sawc("typecheck", "--dump", "--summaries", "--std-root", "std", *extra, rel(path))
    if code != 0:
        return None, "std layers %s: `sawc typecheck` exits %d" % (name, code)
    drops = {m: v for m, v in sections(dropped, drops_header).items() if is_std(m)}
    typed = {m: std_typecheck(v) for m, v in sections(checked, typecheck_header).items() if is_std(m)}
    summaries = [l for l in checked.split("\n") if l.startswith("SUMMARY\tstd.")]
    cut = cut_line(drops.get("std.prelude", []))
    if cut is None:
        return None, "std layers %s: the drops dump holds no program layer's watermarks" % name
    return {"cut": cut, "drops": drops, "typecheck": typed, "summaries": summaries}, None


def first_difference(a, b):
    for k in range(min(len(a), len(b))):
        if a[k] != b[k]:
            return "line %d: %r against %r" % (k + 1, a[k][:160], b[k][:160])
    return "%d lines against %d" % (len(a), len(b))


def run():
    failures = []
    seen = {}
    for name, path, flags in PROGRAMS:
        got, failure = views(name, path, flags)
        if failure:
            failures.append(failure)
            continue
        seen[name] = got
    reference = PROGRAMS[0][0]
    if reference not in seen:
        return failures, {}
    base = seen[reference]
    for name, got in seen.items():
        if name == reference:
            continue
        if got["cut"] != base["cut"]:
            failures.append("std layers %s: the cut differs from %s's: %s against %s"
                            % (name, reference, got["cut"], base["cut"]))
        if got["summaries"] != base["summaries"]:
            failures.append("std layers %s: std's summaries differ from %s's: %s"
                            % (name, reference, first_difference(base["summaries"], got["summaries"])))
        for kind in ("drops", "typecheck"):
            for module in sorted(base[kind]):
                other = got[kind].get(module)
                if other is None:
                    failures.append("std layers %s: no %s section for %s" % (name, kind, module))
                elif other != base[kind][module]:
                    failures.append("std layers %s: %s's %s section differs from %s's: %s"
                                    % (name, module, kind, reference,
                                       first_difference(base[kind][module], other)))
    image_failures, compared = check_images()
    failures += image_failures
    counts = {"std layer programs": len(seen),
              "std layer modules": len(base["drops"]),
              "std images compared": compared}
    return failures, counts


def main():
    failures, counts = run()
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("std layers: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
