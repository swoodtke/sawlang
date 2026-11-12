#!/usr/bin/env python3
"""tools/freestanding_runner.py's verdicts on its prerequisites, against stub tools.

    python tools/test_freestanding_runner.py

Each architecture is skipped, and the suite still passes, when one of ITS tools
is known absent: not on PATH (or, for Xtensa, not under an Espressif tools
root), or no clang `build.pick_clang` would choose for ITS triple. The other
architectures run. When presence cannot be determined the suite fails (exit
4): no PATH at all, a tool that does not answer `--version`, a `SAWC_CLANG`
naming no usable clang, an Espressif emulator that lists no `esp32s3` machine.
Each case runs the runner's `--tools` decision with stub tools first on a PATH
that holds no real ones, `HOME` naming an empty directory (so no
`~/.espressif`), and `HOMEBREW_PREFIX` naming no Homebrew unless the case is
about Homebrew's clang, so nothing is built or booted.

It also holds the runner's soft-float list, the routines a case object
defines itself, equal to the routines LANGUAGE_SPEC.md's Profiles paragraph
names; requires the symbol check to refuse an object that leaves a
soft-float routine undefined; recomputes every row of
`cases/integer_vectors.saw`, the integer helpers' vectors, from its operands;
holds `cases/soft_float_vectors.saw`'s `CHECKSUMS` equal to the checksums
of `compiler/tests/run/softfloat/vectors.txt`, in the runner's order; and
builds a flash image from a synthetic ELF, refusing a segment outside the
flash window.
"""
import os
import re
import shutil
import struct
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
BY_NAME = dict((a["name"], a) for a in ARCHES)
# The runner probes the arches in order, so the first one's QEMU is the one an
# absence or a refusal is reported for.
QEMU = ARCHES[0]["qemu"]
# Where `build.homebrew_clang()` looks, pointed at nothing: a clang outside
# PATH would otherwise answer every case that has the stubs alone.
NO_HOMEBREW = os.path.join(OUT, "no-homebrew")
EMPTY_HOME = os.path.join(OUT, "empty-home")

ANSWERS = "#!/bin/sh\necho '%s 0.0 (stub)'\nexit 0\n"
REFUSES = "#!/bin/sh\necho '%s: cannot run here' >&2\nexit 1\n"
# An Espressif emulator: lists its machine under `-machine help`, as the real
# one does, or answers with machines that are not an ESP32's.
XTENSA_QEMU = "#!/bin/sh\nif [ \"$1\" = -machine ]; then\n  echo 'Supported machines are:'\n  echo '%s'\nfi\nexit 0\n"
ESP32S3_QEMU = XTENSA_QEMU % "esp32s3             Espressif ESP32-S3 platform"
OTHER_QEMU = XTENSA_QEMU % "lm32-evr             LatticeMico32 EVR32 eval system"
XTENSA_QEMU_PATH = os.path.join("tools", "qemu-xtensa", "stub-1", "qemu", "bin", "qemu-system-xtensa")
# The emulators the PATH stubs name, for the rows that find theirs on PATH.
EVERY_QEMU = dict((a["qemu"], ANSWERS) for a in ARCHES if a["qemu_from"] == "path")


def present(over=None):
    """ld.lld and every PATH-found arch's QEMU answering, then the stubs of
    `over` in their place or beside them."""
    found = {"ld.lld": ANSWERS}
    found.update(EVERY_QEMU)
    found.update(over or {})
    return found


def real_clang(name):
    """A clang on this machine that compiles for the arch `name`, as the
    runner's own choice would find it, or None."""
    if name not in BY_NAME:
        return None
    path, _ = build.pick_clang(BY_NAME[name]["triple"], None)
    return path


def espressif_root():
    """The tools root holding this machine's Espressif clang, or None."""
    found = build.espressif_clangs()
    if not found:
        return None
    # ROOT/tools/esp-clang/VERSION/esp-clang/bin/clang
    root = found[0]
    for _ in range(6):
        root = os.path.dirname(root)
    return root


def homebrew_serves(*names):
    """Whether Homebrew's own clang compiles for every arch in `names` and for
    none that has an Espressif tree (so it cannot stand in for it)."""
    path = build.homebrew_clang()
    return os.path.exists(path) and all(
        build.clang_capable(path, BY_NAME[n]["triple"]) == (n != "xtensa") for n in names if n in BY_NAME)


# One case: its name; the stub tools on PATH (name -> body); the PATH entries
# after them or None for no PATH; the `SAWC_CLANG` value; the Espressif tools
# root `IDF_TOOLS_PATH` names (None: unset, "empty": a directory with nothing,
# "emulator": one holding the emulator stub named by `qemu`, "with clang": the
# same beside this machine's real esp-clang tree); whether the real Homebrew
# prefix is used; the extra runner arguments; the exit status; the texts the
# output holds and must not hold; whether it says SKIPPED.
def case(name, stubs, after=(), sawc_clang=None, idf=None, qemu=ESP32S3_QEMU, homebrew=False, args=(),
         status=0, texts=(), absent=(), skipped=False):
    return {"name": name, "stubs": stubs, "after": None if after is None else list(after),
            "sawc_clang": sawc_clang, "idf": idf, "qemu": qemu, "homebrew": homebrew, "args": list(args),
            "status": status, "texts": list(texts), "absent": list(absent), "skipped": skipped}


def cases():
    """The cases, each a dict from `case`, with the ones this machine cannot
    stand up left out and named. Returns (cases, passed-over notes)."""
    out = [
        # Nothing the PATH rows need: every architecture is skipped, which is
        # today's whole-suite skip.
        case("no ld.lld", {}, texts=["ld.lld is not on PATH", "SKIPPED riscv32", "SKIPPED arm64",
                                      "no architecture has its tools"], skipped=True),
        case("no QEMU", {"ld.lld": ANSWERS}, texts=["%s is not on PATH" % QEMU, "no architecture has its tools"],
             skipped=True),
        case("no clang", present(), texts=["no clang compiles for", "no architecture has its tools"],
             skipped=True),
        case("a clang without the target", present({"clang": REFUSES}),
             texts=["does not compile opaque-pointer IR"], skipped=True),
        case("ld.lld does not answer", {"ld.lld": REFUSES}, status=4, texts=["so whether it runs is unknown"]),
        case("QEMU does not answer", present({QEMU: REFUSES}), status=4,
             texts=["so whether it runs is unknown"]),
        case("no PATH", {}, after=None, status=4, texts=["PATH is not set"]),
        case("SAWC_CLANG names nothing", present(), sawc_clang="/nonexistent/clang", status=4,
             texts=["SAWC_CLANG names no clang"]),
    ]
    notes = []
    if "xtensa" in BY_NAME:
        out += [
            # Espressif's tools, as the Xtensa row finds them, are absent: no
            # clang beside none, no emulator under no tools root.
            case("no Espressif tools", present(), idf="empty", args=["--arch", "xtensa"],
                 texts=["SKIPPED xtensa: no clang compiles for xtensa-esp-unknown-elf",
                        "no architecture has its tools"], skipped=True),
            # Every architecture's tools absent, named one by one.
            case("every architecture absent", present(), idf="empty",
                 texts=["SKIPPED riscv32", "SKIPPED arm64", "SKIPPED xtensa", "no architecture has its tools"],
                 skipped=True),
        ]
        xtensa_clang = real_clang("xtensa")
        if xtensa_clang is None:
            notes.append("no Espressif clang here compiles for xtensa-esp-unknown-elf")
        else:
            out += [
                case("Xtensa clang, no emulator", present(), sawc_clang=xtensa_clang, idf="empty",
                     args=["--arch", "xtensa"], texts=["SKIPPED xtensa: qemu-system-xtensa is not under"],
                     skipped=True),
                case("Xtensa emulator lists no esp32s3", present(), sawc_clang=xtensa_clang, idf="emulator",
                     qemu=OTHER_QEMU, args=["--arch", "xtensa"], status=4,
                     texts=["lists no `esp32s3` machine"]),
                case("Xtensa emulator does not answer", present(), sawc_clang=xtensa_clang, idf="emulator",
                     qemu=REFUSES, args=["--arch", "xtensa"], status=4, texts=["so whether it runs is unknown"]),
                case("Xtensa present", present(), sawc_clang=xtensa_clang, idf="emulator",
                     args=["--arch", "xtensa"], texts=["every prerequisite is present"]),
            ]
        if homebrew_serves("riscv32", "arm64", "xtensa"):
            # Xtensa's tools absent and the others present: the others run,
            # Xtensa is skipped by name, each row choosing its own clang.
            out.append(case("Xtensa absent, the others present", present(), idf="empty", homebrew=True,
                            texts=["SKIPPED xtensa: no clang compiles for xtensa-esp-unknown-elf",
                                   "freestanding: riscv32:", "freestanding: arm64:", "2 ran, 1 skipped (xtensa)"],
                            skipped=True))
            if espressif_root() is not None:
                out.append(case("a clang per architecture", present(), idf="with clang", homebrew=True,
                                texts=["every prerequisite is present", "freestanding: xtensa:", "esp-clang"]))
            else:
                notes.append("no Espressif tools root here, for a clang per architecture")
        else:
            notes.append("Homebrew's clang does not serve riscv32 and arm64 and refuse xtensa")
    # One row at a time, each with its own real clang: a clang per architecture,
    # not one that must compile for all of them.
    for arch in ARCHES:
        if arch["qemu_from"] == "espressif":
            continue
        clang = real_clang(arch["name"])
        if clang is None:
            notes.append("no clang here compiles for %s" % arch["triple"])
            continue
        out.append(case("%s present" % arch["name"], present(), sawc_clang=clang, args=["--arch", arch["name"]],
                        texts=["every prerequisite is present"]))
    return out, notes


def run_case(spec):
    """(exit status, output) of the runner under one case."""
    name = spec["name"].replace(" ", "-")
    bin_dir = os.path.join(OUT, name)
    shutil.rmtree(bin_dir, ignore_errors=True)
    os.makedirs(bin_dir)
    for tool, body in spec["stubs"].items():
        path = os.path.join(bin_dir, tool)
        with open(path, "w") as fh:
            fh.write(body % tool)
        os.chmod(path, 0o755)
    os.makedirs(EMPTY_HOME, exist_ok=True)
    env = dict(os.environ)
    env.pop("PATH", None)
    env.pop("SAWC_CLANG", None)
    env.pop("IDF_TOOLS_PATH", None)
    env["HOME"] = EMPTY_HOME
    env["HOMEBREW_PREFIX"] = os.environ.get("HOMEBREW_PREFIX", "") if spec["homebrew"] else NO_HOMEBREW
    if spec["homebrew"] and not env["HOMEBREW_PREFIX"]:
        env.pop("HOMEBREW_PREFIX")
    if spec["after"] is not None:
        env["PATH"] = os.pathsep.join([bin_dir] + spec["after"])
    if spec["sawc_clang"] is not None:
        env["SAWC_CLANG"] = spec["sawc_clang"]
    if spec["idf"] is not None:
        root = os.path.join(bin_dir, "idf")
        os.makedirs(root)
        if spec["idf"] in ("emulator", "with clang"):
            qemu = os.path.join(root, XTENSA_QEMU_PATH)
            os.makedirs(os.path.dirname(qemu))
            with open(qemu, "w") as fh:
                fh.write(spec["qemu"] % "qemu-system-xtensa" if "%s" in spec["qemu"] else spec["qemu"])
            os.chmod(qemu, 0o755)
        if spec["idf"] == "with clang":
            os.makedirs(os.path.join(root, "tools"), exist_ok=True)
            os.symlink(os.path.join(espressif_root(), "tools", "esp-clang"), os.path.join(root, "tools", "esp-clang"))
        env["IDF_TOOLS_PATH"] = root
    r = subprocess.run([sys.executable, RUNNER, "--tools"] + spec["args"], cwd=REPO, env=env, capture_output=True,
                       text=True, timeout=180)
    return r.returncode, r.stdout + r.stderr


def flash_problems():
    """Why `flash_image` does not do what its docstring says, or []: a
    synthetic ELF with the magic words and one segment in the window builds an
    image holding both; a segment outside the window, or no magic, is a
    ToolError naming what is wrong."""
    arch = {"flash_base": 0x42000000}
    problems = []

    def elf(segments):
        header = bytearray(52)
        header[0:4] = b"\x7fELF"
        header[4] = 1
        header[5] = 1
        struct.pack_into("<I", header, 28, 52)
        struct.pack_into("<HH", header, 42, 32, len(segments))
        body = bytearray()
        phs = bytearray()
        data_at = 52 + 32 * len(segments)
        for paddr, data in segments:
            phs += struct.pack("<8I", 1, data_at + len(body), paddr, paddr, len(data), len(data), 5, 4)
            body += data
        return bytes(header + phs + body)

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "synthetic.elf")
    image = os.path.join(OUT, "synthetic.flash.bin")
    magic = freestanding_runner.FLASH_MAGIC

    def build_image(segments):
        with open(path, "wb") as fh:
            fh.write(elf(segments))
        try:
            freestanding_runner.flash_image(path, arch, image)
        except freestanding_runner.ToolError as e:
            return str(e)
        return None

    said = build_image([(0x42000400, magic + b"\x06\x00\x00\x00")])
    if said is not None:
        problems.append("flash_image refuses a good image: %s" % said)
    else:
        with open(image, "rb") as fh:
            flash = fh.read()
        if len(flash) != freestanding_runner.FLASH_BYTES or flash[0x400:0x40C] != magic + b"\x06\x00\x00\x00" \
                or flash[0:0x400] != b"\xff" * 0x400:
            problems.append("flash_image's image is not 4 MiB of 0xFF holding the segment at its offset")
    said = build_image([(0x42000400, magic), (0x3FC8C000, b"\x01\x02\x03\x04")])
    if said is None or "0x3fc8c000" not in said or "outside the flash window" not in said:
        problems.append("flash_image accepts a segment at 0x3FC8C000, or does not name it: %s" % said)
    said = build_image([(0x42000400, magic), (0x42000000 + freestanding_runner.FLASH_BYTES - 2, b"\x01\x02\x03\x04")])
    if said is None or "outside the flash window" not in said:
        problems.append("flash_image accepts a segment that ends past the window: %s" % said)
    said = build_image([(0x42000408, b"\x06\x00\x00\x00")])
    if said is None or "magic" not in said:
        problems.append("flash_image accepts an image with no magic words: %s" % said)
    return problems


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
    failures = []
    ran = 0
    specs, notes = cases()
    for note in notes:
        print("freestanding runner: passed over a case: %s" % note)
    for spec in specs:
        ran += 1
        status, said = run_case(spec)
        if status != spec["status"]:
            failures.append("%s: `--tools` exits %d, not %d: %s" % (spec["name"], status, spec["status"],
                                                                    said.strip()[:600]))
        for text in spec["texts"]:
            if text not in said:
                failures.append("%s: the output does not say %r: %s" % (spec["name"], text, said.strip()[:600]))
        for text in spec["absent"]:
            if text in said:
                failures.append("%s: the output says %r: %s" % (spec["name"], text, said.strip()[:600]))
        if spec["skipped"] and "SKIPPED" not in said:
            failures.append("%s: passes without saying it SKIPPED: %s" % (spec["name"], said.strip()[:400]))
        if not spec["skipped"] and "SKIPPED" in said:
            failures.append("%s: says it SKIPPED: %s" % (spec["name"], said.strip()[:400]))
    failures += soft_float_problems()
    failures += vector_problems()
    failures += checksum_problems()
    failures += flash_problems()
    for failure in failures:
        print(failure)
    print("freestanding runner: %s: %d tool-decision cases, the soft-float list and symbol check, the integer helpers' "
          "vectors, the soft-float checksums" % ("FAIL (%d)" % len(failures) if failures else "ok", ran))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
