#!/usr/bin/env python3
"""The Blade lane: Blade built by sawc, self-built, and run over its packages.

    tools/blade_lane.py

Steps, each printed, the first failure ending the run:
  1. sawc builds Blade from blade/ (`build_blade`).
  2. That Blade builds blade/ itself.
  3. The self-built Blade runs `blade test` in blade/ and in each package
     under libs/.
  4. The CPU and feature list Blade gives the C half of an Xtensa image equal
     the ones sawc writes for the Saw half (`--emit-ll`, no clang needed).
  5. Blade refuses an unknown flag or word; `--module-path`, `--out-dir` and
     `--linker-script` reach the build and its freshness check.
  6. `blade new` and `blade run` make and run a package in a directory under
     `.build/`.

Every compile goes through `build.SAWC`, handed to Blade as `SAWC`. The suite
lock is not taken here: the battery and the patch gate run this inside the lock
their caller already holds. Child processes start through tools/child_groups.py.

ENTRY POINTS:
  build_blade
  ensure_blade
  blade_environment
"""
import os
import re
import shutil
import struct
import sys
import subprocess
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import build  # noqa: E402
import child_groups  # noqa: E402
import patch_gate  # noqa: E402

BLADE_DIR = os.path.join(REPO, "blade")
LIBS_DIR = os.path.join(REPO, "libs")
LIBRARIES = ("semver", "toml", "imgformat")
WORK_DIR = os.path.join(build.BUILD_DIR, "blade_lane")
BLADE_BINARY = os.path.join(WORK_DIR, "blade")
SMOKE_DIR = os.path.join(WORK_DIR, "smoke")
SELF_BUILT = os.path.join(BLADE_DIR, ".build", "host", "blade")
SMOKE_PACKAGE = "smoke_app"
XTENSA_TRIPLE = "xtensa-esp-unknown-elf"
BUILD_TIMEOUT_S = 900
TEST_TIMEOUT_S = 900
SMOKE_TIMEOUT_S = 300

# Blade's own module path: its package and the three libraries it imports.
MODULE_PATHS = (
    ("blade", os.path.join(BLADE_DIR, "src")),
    ("toml", os.path.join(LIBS_DIR, "toml", "src")),
    ("semver", os.path.join(LIBS_DIR, "semver", "src")),
    ("imgformat", os.path.join(LIBS_DIR, "imgformat", "src")),
)

_build_lock = threading.Lock()
_built = []


def blade_environment(extra=None):
    """The environment a Blade child runs in: this checkout's sawc as `SAWC`."""
    env = dict(os.environ)
    env["SAWC"] = build.SAWC
    if extra:
        env.update(extra)
    return env


def run(argv, timeout, cwd=REPO, env=None):
    """(exit status or None on a timeout, combined output) of `argv`."""
    try:
        proc = child_groups.start(argv, cwd=cwd, env=env if env is not None else blade_environment(),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, errors="replace")
    except OSError as e:
        return 127, "%s: %s" % (argv[0], e)
    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        child_groups.kill(proc)
        out, _ = proc.communicate()
        code = None
    finally:
        child_groups.forget(proc)
    return code, out or ""


def blade_build_arguments(out, compiler=None, flags=()):
    """The argv that has `compiler` (default `build.SAWC`) build Blade into
    `out`; `flags` follow `build`. The compile benchmark shares it."""
    argv = [compiler or build.SAWC, "build"] + list(flags) + [os.path.join(BLADE_DIR, "src", "main.saw"), "-o", out]
    for name, directory in MODULE_PATHS:
        argv += ["--module-path", "%s=%s" % (name, directory)]
    return argv


def build_blade():
    """Compile Blade with sawc into `BLADE_BINARY`: (ok, output)."""
    os.makedirs(WORK_DIR, exist_ok=True)
    code, out = run(blade_build_arguments(BLADE_BINARY), BUILD_TIMEOUT_S)
    return code == 0, out


def ensure_blade():
    """`BLADE_BINARY`, built once per process; raises RuntimeError when sawc cannot build it."""
    with _build_lock:
        if not _built:
            ok, out = build_blade()
            if not ok:
                raise RuntimeError("sawc does not build Blade\n%s" % out)
            _built.append(BLADE_BINARY)
    return BLADE_BINARY


class Failure(Exception):
    pass


def step(title, argv, timeout, cwd=REPO, expect=None):
    """Run one step, print its title, and raise Failure unless it exits 0 and
    (when given) its output holds `expect`."""
    print("blade: %s" % title, flush=True)
    code, out = run(argv, timeout, cwd=cwd)
    if code is None:
        raise Failure("%s timed out after %ds\n%s" % (title, timeout, out))
    if code != 0:
        raise Failure("%s exited %d\n%s" % (title, code, out))
    if expect is not None and expect not in out:
        raise Failure("%s did not print %r\n%s" % (title, expect, out))
    return out


def tests_passed(title, binary, cwd):
    out = step(title, [binary, "test"], TEST_TIMEOUT_S, cwd=cwd)
    summary = [line for line in out.splitlines() if line.startswith("test result:")]
    print("      " + (summary[-1] if summary else "(no summary line)"), flush=True)
    if not summary or " 0 failed" not in summary[-1]:
        raise Failure("%s: no passing summary\n%s" % (title, out))


def blade_xtensa_defaults():
    """(CPU, feature list) Blade gives the C half of an Xtensa image, read out of
    blade/src/sosimg.saw: the `mcpu` of the xtensa branch of `toolchain_defaults`
    and the literal `xtensa_native_features` returns."""
    with open(os.path.join(BLADE_DIR, "src", "sosimg.saw"), encoding="utf-8") as f:
        text = f.read()
    features = re.search(r'func xtensa_native_features\(\) -> String \{\s*"([^"]*)"\s*\}', text)
    branch = re.search(r'target\.starts_with\("xtensa"\)\s*\{.*?mcpu:\s*"([^"]*)"', text, re.S)
    if not features or not branch:
        raise Failure("blade/src/sosimg.saw no longer states the Xtensa defaults where the lane reads them")
    return branch.group(1), features.group(1)


def check_xtensa_drift():
    """Blade's CPU and feature list for the C half of an Xtensa image equal the
    `target-cpu` and `target-features` sawc compiles the Saw half with. `--emit-ll`
    needs no clang, so this runs everywhere."""
    cpu, features = blade_xtensa_defaults()
    os.makedirs(WORK_DIR, exist_ok=True)
    source = os.path.join(WORK_DIR, "xtensa_drift.saw")
    with open(source, "w", encoding="utf-8") as f:
        f.write('@export("drift")\nfunc drift() -> Int { 1 }\n')
    out = step("Blade's Xtensa C features match sawc's",
               [build.SAWC, "build", "--freestanding", "--target", XTENSA_TRIPLE, "--emit-ll", source],
               BUILD_TIMEOUT_S)
    found = set(re.findall(r'"target-features"="([^"]*)"', out))
    if found != {features}:
        raise Failure("sawc compiles the Saw half of an %s image with target-features %s, and Blade gives the C half %r"
                      % (XTENSA_TRIPLE, sorted(found), features))
    cpus = set(re.findall(r'"target-cpu"="([^"]*)"', out))
    if cpus != {cpu}:
        raise Failure("sawc compiles the Saw half of an %s image for cpu %s, and Blade gives the C half %r"
                      % (XTENSA_TRIPLE, sorted(cpus), cpu))


def check_blade_finds_tools():
    """With `SOS_CLANG` and `SOS_LD` unset, Blade builds `tests/freestanding/bladepkg`
    for each bare-metal target sawc has a record for, with the clang and `ld.lld` `sawc tools`
    names; a target with no record is skipped, saying so. With `SOS_CLANG` naming a program
    that does not exist the build fails to launch it, so the variable still wins."""
    package = os.path.join(REPO, "tests", "freestanding", "bladepkg")
    unset = blade_environment()
    for name in ("SOS_CLANG", "SOS_LD"):
        unset.pop(name, None)
    recorded = []
    for triple in ("riscv32-unknown-none-elf", XTENSA_TRIPLE):
        record = os.path.join(os.path.dirname(build.SAWC), "sawc-runtime-%s.txt" % triple)
        if not os.path.exists(record):
            print("blade: no sawc record for %s: Blade's own search of the tools is not checked for it" % triple,
                  flush=True)
            continue
        recorded.append(triple)
        shutil.rmtree(os.path.join(package, ".build", triple), ignore_errors=True)
        print("blade: blade build --target %s, SOS_CLANG and SOS_LD unset" % triple, flush=True)
        code, out = run([SELF_BUILT, "build", "--target", triple], BUILD_TIMEOUT_S, cwd=package, env=unset)
        if code != 0:
            raise Failure("blade build --target %s with SOS_CLANG and SOS_LD unset exited %s\n%s" % (triple, code, out))
        if not os.path.exists(os.path.join(package, ".build", triple, "fsblade.sosimg")):
            raise Failure("blade build --target %s left no image\n%s" % (triple, out))
    if not recorded:
        return
    wrong = dict(unset)
    wrong["SOS_CLANG"] = os.path.join(WORK_DIR, "no-such-clang")
    shutil.rmtree(os.path.join(package, ".build", recorded[0]), ignore_errors=True)
    print("blade: blade build --target %s, SOS_CLANG naming no program" % recorded[0], flush=True)
    code, out = run([SELF_BUILT, "build", "--target", recorded[0]], BUILD_TIMEOUT_S, cwd=package, env=wrong)
    if code == 0 or "could not launch clang" not in out:
        raise Failure("SOS_CLANG naming no program did not stop the build with `could not launch clang`\n%s" % out)


def run_blade(binary, args, cwd, env=None):
    """(exit status, output) of `binary args` in `cwd`; a timeout is a Failure."""
    code, out = run([binary] + list(args), BUILD_TIMEOUT_S, cwd=cwd, env=env)
    if code is None:
        raise Failure("blade %s timed out\n%s" % (" ".join(args), out))
    return code, out


def blade_ok(binary, args, cwd, expect, env=None):
    """Run `blade args` expecting exit 0 and `expect` in the output; the output."""
    code, out = run_blade(binary, args, cwd, env)
    if code != 0 or expect not in out:
        raise Failure("blade %s exited %s and did not print %r\n%s" % (" ".join(args), code, expect, out))
    return out


def blade_refused(binary, args, cwd, text, env=None):
    """Run `blade args` expecting a non-zero exit and `text` in the output."""
    code, out = run_blade(binary, args, cwd, env)
    if code == 0 or text not in out:
        raise Failure("blade %s exited %s and did not refuse with %r\n%s" % (" ".join(args), code, text, out))


def check_blade_refuses_unknown_words(binary=None):
    """Blade refuses what it does not know instead of building: an unknown or
    misspelled flag, a stray word, a missing value, a flag no subcommand takes,
    and `--linker-script` on a package that builds no image."""
    binary = binary or SELF_BUILT
    work = os.path.join(WORK_DIR, "scan")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    blade_ok(binary, ["new", "app"], work, "Created")
    package = os.path.join(work, "app")
    refusals = (
        (["build", "--x"], "blade build: unknown flag `--x`"),
        (["build", "--targt", "x"], "blade build: unknown flag `--targt`"),
        (["build", "stray"], "blade build takes no arguments, got `stray`"),
        (["build", "--target"], "blade build: `--target` requires a value"),
        (["build", "--force", "--force"], "blade build: `--force` was given twice"),
        (["build", "--module-path", "nonequals"], "blade build: `--module-path nonequals` must be NAME=DIR"),
        (["build", "--module-path", "a=nodir"], "no such directory `nodir`"),
        (["build", "--linker-script", "x.ld"], "`--linker-script` applies to an image build"),
        (["clean", "--out-dir", "d"], "blade clean: unknown flag `--out-dir`"),
        (["test", "--x"], "blade test: unknown flag `--x`"),
        (["tree", "stray"], "blade tree takes no arguments, got `stray`"),
        (["update", "--x"], "blade update: unknown flag `--x`"),
        (["new", "a", "b"], "blade new: unexpected argument `b`"),
        (["add", "dep"], "blade add requires --path <dir> or --git <url>"),
    )
    for args, text in refusals:
        print("blade: blade %s is refused" % " ".join(args), flush=True)
        blade_refused(binary, args, package, text)
    if os.path.exists(os.path.join(package, ".build")):
        raise Failure("a refused command left a .build directory")
    print("blade: blade build --help prints the help", flush=True)
    blade_ok(binary, ["build", "--help"], package, "--out-dir")
    if os.path.exists(os.path.join(package, ".build")):
        raise Failure("`blade build --help` built something")


def check_blade_module_path(binary=None):
    """`blade build --module-path NAME=DIR` reaches sawc: a package importing a
    module it has no dependency for is refused by sawc without the flag and builds
    with it; changing a source under DIR rebuilds, and an unchanged one is up to
    date. Refused: a NAME a dependency already has, a DIR that is no directory."""
    binary = binary or SELF_BUILT
    work = os.path.join(WORK_DIR, "modpath")
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(os.path.join(BLADE_DIR, "tests", "fixtures", "modpath"), work)
    package = os.path.join(work, "app")
    flag = ["--module-path", "shared=../shared"]
    print("blade: blade build without --module-path is refused by sawc", flush=True)
    blade_refused(binary, ["build"], package, "sawc failed")
    print("blade: blade build --module-path shared=../shared", flush=True)
    blade_ok(binary, ["build"] + flag, package, "Finished .build/host/modapp\n")
    code, out = run([os.path.join(package, ".build", "host", "modapp")], SMOKE_TIMEOUT_S, cwd=package)
    if code != 0 or "42" not in out:
        raise Failure("the built program did not print 42\n%s" % out)
    blade_ok(binary, ["build"] + flag, package, "(up to date)")
    print("blade: a changed module path NAME is not up to date", flush=True)
    blade_refused(binary, ["build", "--module-path", "other=../shared"], package, "sawc failed")
    blade_ok(binary, ["build"] + flag, package, "(up to date)")
    print("blade: a second target into one out-dir is not up to date", flush=True)
    blade_ok(binary, ["build", "--out-dir", "o"] + flag, package, "Compiling")
    _, out = run_blade(binary, ["build", "--target", "aarch64-unknown-none-elf", "--out-dir", "o"] + flag, package)
    if "up to date" in out:
        raise Failure("a build for another target answered up to date for the one in the out-dir\n%s" % out)
    blade_ok(binary, ["build", "--out-dir", "o"] + flag, package, "(up to date)")
    print("blade: --out-dir=-x keeps the directory a directory", flush=True)
    blade_ok(binary, ["build", "--out-dir=-x"] + flag, package, "Finished ./-x/modapp")
    if not os.path.exists(os.path.join(package, "-x", "modapp")):
        raise Failure("--out-dir=-x left no binary in -x")
    with open(os.path.join(work, "shared", "sub.saw"), "w", encoding="utf-8") as f:
        f.write("public func more() -> Int {\n    1\n}\n")
    print("blade: a new source under the module path rebuilds", flush=True)
    blade_ok(binary, ["build"] + flag, package, "Compiling modapp")
    with open(os.path.join(work, "shared", "lib.saw"), "a", encoding="utf-8") as f:
        f.write("// edited\n")
    print("blade: a changed source under the module path rebuilds", flush=True)
    blade_ok(binary, ["build"] + flag, package, "Compiling modapp")
    blade_ok(binary, ["build"] + flag, package, "(up to date)")
    blade_refused(binary, ["build", "--module-path", "shared=src/main.saw"], package, "is not a directory")
    dependency = os.path.join(work, "dep_app")
    shutil.copytree(os.path.join(BLADE_DIR, "tests", "fixtures", "buildapp"), dependency)
    print("blade: --module-path naming a dependency is refused", flush=True)
    blade_refused(binary, ["build", "--module-path", "greet=src"], os.path.join(dependency, "app"),
                  "names a dependency already")


def elf_entry(path):
    """The entry address of the 32-bit little-endian ELF at `path`."""
    with open(path, "rb") as f:
        header = f.read(28)
    return struct.unpack_from("<I", header, 24)[0]


def image_package():
    """A fresh copy of `tests/freestanding` under WORK_DIR, the Blade case's
    package inside it: (package directory, directory holding it)."""
    root = os.path.join(WORK_DIR, "images")
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(os.path.join(REPO, "tests", "freestanding"), root, ignore=shutil.ignore_patterns(".build"))
    return os.path.join(root, "bladepkg"), root


def has_sawc_record(triple):
    return os.path.exists(os.path.join(os.path.dirname(build.SAWC), "sawc-runtime-%s.txt" % triple))


def rewrite_text_address(script, address):
    """Rewrite the `. = 0x...;` line that opens SECTIONS in the linker script at `script`."""
    with open(script, encoding="utf-8") as f:
        text = f.read()
    text, count = re.subn(r"(SECTIONS \{\s*\. = )0x[0-9a-fA-F]+;", r"\g<1>%s;" % address, text, count=1)
    if count != 1:
        raise Failure("%s no longer opens SECTIONS with `. = <address>;`" % script)
    with open(script, "w", encoding="utf-8") as f:
        f.write(text)


def check_blade_out_dir_and_linker_script(binary=None):
    """On the Blade case's package: `--out-dir` puts everything in the named
    directory (no `.build` is made), each out-dir reports its own freshness, and a
    build into a second target's out-dir is its own; `--linker-script` overrides
    the manifest's, and its content, like the manifest-named script's, is part of
    the freshness (a changed script relinks, an unchanged one is up to date). The
    entry address of each image is the one its script gives."""
    binary = binary or SELF_BUILT
    triple = "riscv32-unknown-none-elf"
    if not has_sawc_record(triple):
        print("blade: no sawc record for %s: --out-dir and --linker-script are not checked" % triple, flush=True)
        return
    package, root = image_package()
    hal = os.path.join(root, "hal", "riscv32")
    image = "fsblade.sosimg"
    first, second = os.path.join(root, "out1"), os.path.join(root, "out2")
    print("blade: blade build --target %s --out-dir out1" % triple, flush=True)
    out = blade_ok(binary, ["build", "--target", triple, "--out-dir", first], package, "Finished %s" % os.path.join(first, image))
    if "up to date" in out:
        raise Failure("a first build into a new out-dir said it was up to date\n%s" % out)
    if os.path.exists(os.path.join(package, ".build")):
        raise Failure("--out-dir left a .build directory in the package")
    for name in (image, "fsblade.elf", "build-hash"):
        if not os.path.exists(os.path.join(first, name)):
            raise Failure("--out-dir left no %s in %s" % (name, first))
    blade_ok(binary, ["build", "--target", triple, "--out-dir", first], package, "(up to date)")
    print("blade: a second out-dir reports its own freshness", flush=True)
    out = blade_ok(binary, ["build", "--target", triple, "--out-dir", second], package, "Finished %s" % os.path.join(second, image))
    if "up to date" in out:
        raise Failure("a build into a second out-dir said it was up to date\n%s" % out)
    blade_ok(binary, ["build", "--target", triple, "--out-dir", second], package, "(up to date)")
    blade_ok(binary, ["build", "--target", triple, "--out-dir", first], package, "(up to date)")
    other = "aarch64-unknown-none-elf"
    if has_sawc_record(other):
        third = os.path.join(root, "out3")
        print("blade: blade build --target %s --out-dir out3" % other, flush=True)
        out = blade_ok(binary, ["build", "--target", other, "--out-dir", third], package, "Finished %s" % os.path.join(third, image))
        if "up to date" in out:
            raise Failure("a build for a second target said it was up to date\n%s" % out)
        blade_ok(binary, ["build", "--target", other, "--out-dir", third], package, "(up to date)")
        blade_ok(binary, ["build", "--target", triple, "--out-dir", first], package, "(up to date)")

    elf = os.path.join(first, "fsblade.elf")
    manifest_address = elf_entry(elf)
    script_a = os.path.join(hal, "a.ld")
    script_b = os.path.join(hal, "b.ld")
    shutil.copy(os.path.join(hal, "link.ld"), script_a)
    shutil.copy(os.path.join(hal, "link.ld"), script_b)
    rewrite_text_address(script_b, "0x80010000")
    flags = ["build", "--target", triple]
    print("blade: --linker-script places the image where each script says", flush=True)
    blade_ok(binary, flags + ["--out-dir", first, "--linker-script", script_a], package, "Compiling")
    if elf_entry(elf) != manifest_address:
        raise Failure("a copy of the manifest's script linked to a different entry")
    blade_ok(binary, flags + ["--out-dir", second, "--linker-script", script_b], package, "Compiling")
    entry_b = elf_entry(os.path.join(second, "fsblade.elf"))
    if entry_b != 0x80010000 or entry_b == manifest_address:
        raise Failure("--linker-script b.ld linked to entry %#x, wanted 0x80010000" % entry_b)
    blade_ok(binary, flags + ["--out-dir", first, "--linker-script", script_a], package, "(up to date)")
    print("blade: a changed --linker-script file relinks", flush=True)
    rewrite_text_address(script_a, "0x80020000")
    blade_ok(binary, flags + ["--out-dir", first, "--linker-script", script_a], package, "Compiling")
    if elf_entry(elf) != 0x80020000:
        raise Failure("the edited script was not linked: entry %#x, wanted 0x80020000" % elf_entry(elf))
    print("blade: switching --linker-script on one out-dir relinks", flush=True)
    blade_ok(binary, flags + ["--out-dir", first, "--linker-script", script_b], package, "Compiling")
    if elf_entry(elf) != 0x80010000:
        raise Failure("the switched script was not linked: entry %#x" % elf_entry(elf))
    print("blade: a changed manifest-named linker script relinks", flush=True)
    blade_ok(binary, flags + ["--out-dir", second], package, "Compiling")
    blade_ok(binary, flags + ["--out-dir", second], package, "(up to date)")
    rewrite_text_address(os.path.join(hal, "link.ld"), "0x80030000")
    blade_ok(binary, flags + ["--out-dir", second], package, "Compiling")
    if elf_entry(os.path.join(second, "fsblade.elf")) != 0x80030000:
        raise Failure("the edited manifest script was not linked")
    blade_refused(binary, flags + ["--linker-script", os.path.join(hal, "none.ld")], package, "does not exist")
    blade_refused(binary, flags + ["--linker-script", hal], package, "is a directory")


def elf_machine(path):
    """The `e_machine` field (16 bits at offset 18) of the ELF at `path`."""
    with open(path, "rb") as f:
        header = f.read(20)
    return struct.unpack_from("<H", header, 18)[0]


def check_blade_out_dir_names_target(binary=None):
    """One out-dir and one `--linker-script` given to two targets: each build
    compiles and links for its own target, so the second never answers
    `(up to date)` for the first (the target is part of the freshness)."""
    binary = binary or SELF_BUILT
    riscv, arm = "riscv32-unknown-none-elf", "aarch64-unknown-none-elf"
    missing = [t for t in (riscv, arm) if not has_sawc_record(t)]
    if missing:
        print("blade: no sawc record for %s: one out-dir shared by two targets is not checked" % ", ".join(missing),
              flush=True)
        return
    package, root = image_package()
    script = os.path.join(root, "hal", "riscv32", "shared.ld")
    shutil.copy(os.path.join(root, "hal", "riscv32", "link.ld"), script)
    out_dir = os.path.join(root, "shared_out")
    elf = os.path.join(out_dir, "fsblade.elf")
    for target, machine in ((riscv, 243), (arm, 183), (riscv, 243)):
        print("blade: blade build --target %s into the shared out-dir compiles for it" % target, flush=True)
        out = blade_ok(binary, ["build", "--target", target, "--out-dir", out_dir, "--linker-script", script],
                       package, "Compiling")
        if "up to date" in out:
            raise Failure("a build for %s into an out-dir another target built said it was up to date\n%s" % (target, out))
        if elf_machine(elf) != machine:
            raise Failure("the image built for %s has e_machine %d, wanted %d" % (target, elf_machine(elf), machine))


def check_blade_image_module_path(binary=None):
    """`--module-path` reaches the sawc compile of an image build: the image
    package's source imports a module only the flag names. Without the flag sawc
    refuses it; with it the image builds, an unchanged module is up to date and
    an edit under it rebuilds. The tracked `tests/freestanding/bladepkg` is not
    changed: the lane builds a copy."""
    binary = binary or SELF_BUILT
    triple = "riscv32-unknown-none-elf"
    if not has_sawc_record(triple):
        print("blade: no sawc record for %s: --module-path on an image build is not checked" % triple, flush=True)
        return
    package, root = image_package()
    module = os.path.join(root, "extra")
    os.makedirs(module)
    with open(os.path.join(module, "lib.saw"), "w", encoding="utf-8") as f:
        f.write("public func answer() -> Int {\n    42\n}\n")
    source = os.path.join(package, "src", "main.saw")
    with open(source, encoding="utf-8") as f:
        text = f.read()
    text = text.replace("import fscore.*\n", "import fscore.*\nimport extra\n", 1)
    text = text.replace('    finish("blade_target")', '    check_value("blade_module_path", extra.answer(), 42)\n    finish("blade_target")', 1)
    if "import extra" not in text or "extra.answer()" not in text:
        raise Failure("%s no longer has the lines the lane edits" % source)
    with open(source, "w", encoding="utf-8") as f:
        f.write(text)
    flags = ["build", "--target", triple]
    flag = ["--module-path", "extra=../extra"]
    print("blade: an image importing a module only --module-path reaches is refused without it", flush=True)
    blade_refused(binary, flags, package, "sawc failed")
    print("blade: blade build --target %s --module-path extra=../extra" % triple, flush=True)
    blade_ok(binary, flags + flag, package, "Compiling")
    blade_ok(binary, flags + flag, package, "(up to date)")
    with open(os.path.join(module, "lib.saw"), "a", encoding="utf-8") as f:
        f.write("// edited\n")
    print("blade: a changed source under the image's module path rebuilds", flush=True)
    blade_ok(binary, flags + flag, package, "Compiling")


def lane():
    ok, out = (True, "") if build.handed_down() else build.build_sawc()
    if not ok:
        print("%s\nblade: FAIL: sawc does not build" % out)
        return 1
    try:
        print("blade: sawc builds Blade", flush=True)
        ok, out = build_blade()
        if not ok:
            raise Failure("sawc does not build Blade\n%s" % out)
        if os.path.exists(SELF_BUILT):
            os.remove(SELF_BUILT)
        step("Blade builds itself", [BLADE_BINARY, "build"], BUILD_TIMEOUT_S, cwd=BLADE_DIR)
        if not os.path.exists(SELF_BUILT):
            raise Failure("the self-build left no %s" % SELF_BUILT)
        tests_passed("blade test in blade/", SELF_BUILT, BLADE_DIR)
        for lib in LIBRARIES:
            tests_passed("blade test in libs/%s" % lib, SELF_BUILT, os.path.join(LIBS_DIR, lib))
        check_xtensa_drift()
        check_blade_finds_tools()
        check_blade_refuses_unknown_words()
        check_blade_module_path()
        check_blade_out_dir_and_linker_script()
        check_blade_out_dir_names_target()
        check_blade_image_module_path()
        shutil.rmtree(SMOKE_DIR, ignore_errors=True)
        os.makedirs(SMOKE_DIR)
        step("blade new", [SELF_BUILT, "new", SMOKE_PACKAGE], SMOKE_TIMEOUT_S, cwd=SMOKE_DIR,
             expect="Created")
        step("blade run", [SELF_BUILT, "run"], SMOKE_TIMEOUT_S, cwd=os.path.join(SMOKE_DIR, SMOKE_PACKAGE),
             expect="Hello, %s!" % SMOKE_PACKAGE)
    except Failure as e:
        print("blade: FAIL: %s" % e)
        return 1
    print("blade: ok")
    return 0


if __name__ == "__main__":
    child_groups.install()
    # sawc's builds of Blade, and Blade's own, share the run's sawc cache.
    patch_gate.gate_cache()
    sys.exit(lane())
