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
  5a. A dependency whose path holds a backslash or a double quote, or whose key
     needs quotes, resolves, locks and builds twice; a manifest the resolver
     cannot read is refused with its path, position and reason.
  5b. Each input a build reads or chooses (nested sources, a root main.saw, a
     dependency's manifest, native units, the tool and compiler choices, the
     compiler's version) changes the freshness check.
  5c. A package with `no-hidden-alloc = true` has `blade build` and `blade test`
     refuse an interpolation with sawc's diagnostic, builds without the key, and
     rebuilds when the key changes; a dependency's key does not reach its dependents.
  5d. A package with `max-task-frame = "64KiB"` has `blade build` and `blade test`
     refuse a task whose frame is over it, builds with a larger key or none, rebuilds
     when the key changes, refuses a value that is not a size; a dependency's key does
     not reach its dependents.
  5e. A path dependency's `[native]` prebuilt object, archive and library (in a directory whose
     name holds a space and quotes) reach `blade build`, `blade run` and `blade test`; a table of
     another triple is left alone; rewriting the object or the archive rebuilds; a `[native]`
     it cannot honour, or a file it names that is not there, is refused.
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


def check_blade_tree_status(binary=None):
    """`blade tree` exits 0 for a resolved graph and non-zero, printing the
    error, for a dependency that cannot be read."""
    binary = binary or SELF_BUILT
    work = os.path.join(WORK_DIR, "tree")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    blade_ok(binary, ["new", "app"], work, "Created")
    package = os.path.join(work, "app")
    print("blade: blade tree on a package with no dependencies", flush=True)
    blade_ok(binary, ["tree"], package, "(no dependencies)")
    append_text(os.path.join(package, "Saw.toml"), '\n[dependencies]\nghost = { path = "../ghost" }\n')
    print("blade: blade tree after a resolution error exits non-zero", flush=True)
    blade_refused(binary, ["tree"], package, "error: cannot read manifest for `ghost`")


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


def append_text(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def write_script(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o755)


def fake_compiler(directory, version="sawc 9.0.0"):
    """A `SAWC` script in `directory` that compiles with `build.SAWC`; its
    `--version` is the first line of `version.txt` beside it (`FAIL` exits 1,
    `EMPTY` prints nothing) and `sawc tools` prints `tools.txt` when there is
    one. Its `--build-id` refuses the flag as usage (status 2, as an older
    `sawc` does) until `set_build_id` writes `build-id.txt`: its text is the
    answer, `FAIL` prints a line and exits 1, `EMPTY` prints nothing and
    `MANY` prints two lines.
    Returns the script's path."""
    os.makedirs(directory, exist_ok=True)
    script = os.path.join(directory, "fakesawc.sh")
    write_script(script, (
        '#!/bin/bash\nD=$(dirname "$0")\n'
        'if [ "$1" = "--build-id" ]; then\n'
        '  if [ ! -f "$D/build-id.txt" ]; then exit 2; fi\n'
        '  v=$(cat "$D/build-id.txt")\n'
        '  if [ "$v" = FAIL ]; then echo partial-id; exit 1; fi\n'
        '  if [ "$v" = EMPTY ]; then exit 0; fi\n'
        '  if [ "$v" = MANY ]; then printf "first\\nsecond\\n"; exit 0; fi\n'
        '  echo "$v"; exit 0\n'
        'fi\n'
        'if [ "$1" = "--version" ] && [ -f "$D/version.txt" ]; then\n'
        '  v=$(cat "$D/version.txt")\n'
        '  if [ "$v" = FAIL ]; then exit 1; fi\n'
        '  if [ "$v" = EMPTY ]; then exit 0; fi\n'
        '  echo "$v"; exit 0\n'
        'fi\n'
        'if [ "$1" = tools ] && [ -f "$D/tools.txt" ]; then cat "$D/tools.txt"; exit 0; fi\n'
        'exec "%s" "$@"\n' % build.SAWC))
    set_version(directory, version)
    return script


def set_version(directory, text):
    with open(os.path.join(directory, "version.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")


def set_build_id(directory, text):
    with open(os.path.join(directory, "build-id.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")


def std_copy_compiler(directory):
    """A `SAWC` script in `directory` that is `build.SAWC` compiling against
    the copy of `std/` beside it, and answering `--build-id` for that copy;
    its `--version` is the real one, so only the std copy tells it apart from
    the compiler it wraps. Returns the script's path."""
    os.makedirs(directory, exist_ok=True)
    shutil.copytree(build.STD_ROOT, os.path.join(directory, "std"))
    script = os.path.join(directory, "stdcopysawc.sh")
    write_script(script, (
        '#!/bin/bash\nD=$(dirname "$0")\n'
        'case "$1" in\n'
        '  --version) exec "%s" --version;;\n'
        '  --build-id) exec "%s" --build-id --std-root "$D/std";;\n'
        'esac\n'
        'exec "%s" --std-root "$D/std" "$@"\n' % (build.SAWC, build.SAWC, build.SAWC)))
    return script


def stage_switch_compiler(directory, binary):
    """A `SAWC` script in `directory` that runs the binary `which.txt` names;
    `set_stage` points it. Both stages print one version line, so only the
    compiler's identity tells the two apart. Returns the script's path."""
    os.makedirs(directory, exist_ok=True)
    script = os.path.join(directory, "stageswitchsawc.sh")
    write_script(script, '#!/bin/bash\nD=$(dirname "$0")\nexec "$(cat "$D/which.txt")" "$@"\n')
    set_stage(directory, binary)
    return script


def set_stage(directory, binary):
    with open(os.path.join(directory, "which.txt"), "w", encoding="utf-8") as f:
        f.write(binary + "\n")


def rebuilds_after(binary, name, args, package, change, before_env=None, after_env=None):
    """One row of the freshness matrix: a build that is up to date, then `change()` to
    the one input, and the next build prints `Compiling` and not `(up to date)`; an
    unchanged build after that is up to date again."""
    print("blade: a changed %s rebuilds" % name, flush=True)
    code, out = run_blade(binary, args, package, before_env)
    if code != 0:
        raise Failure("blade %s before changing %s exited %s\n%s" % (" ".join(args), name, code, out))
    blade_ok(binary, args, package, "(up to date)", before_env)
    change()
    after_env = after_env if after_env is not None else before_env
    out = blade_ok(binary, args, package, "Compiling", after_env)
    if "(up to date)" in out:
        raise Failure("a changed %s left the build up to date\n%s" % (name, out))
    blade_ok(binary, args, package, "(up to date)", after_env)


def check_blade_freshness_hosted(binary=None):
    """A hosted build is up to date only while every input the build reads or
    chooses is unchanged: a source in a subdirectory of the package's `src` or a
    dependency's `src`, a root `main.saw`, a dependency's `Saw.toml`, the `SAWC`
    command and the compiler's identity, which is `sawc --build-id` (its binary,
    its std and its runtime), or the version for a compiler that refuses the
    flag as usage. A compiler whose identity cannot be read is never up to
    date."""
    binary = binary or SELF_BUILT
    work = os.path.join(WORK_DIR, "freshness")
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(os.path.join(BLADE_DIR, "tests", "fixtures", "freshness"), work)
    package = os.path.join(work, "app")
    root_main = os.path.join(work, "rootmain")
    rows = (
        ("source below the package's src", package, os.path.join(package, "src", "net", "tcp.saw"), "// edited\n"),
        ("source below a dependency's src", package, os.path.join(work, "lib", "src", "inner", "helper.saw"), "// edited\n"),
        ("dependency Saw.toml", package, os.path.join(work, "lib", "Saw.toml"), "# edited\n"),
        ("root main.saw", root_main, os.path.join(root_main, "main.saw"), "// edited\n"),
    )
    for name, directory, path, text in rows:
        rebuilds_after(binary, name, ["build"], directory, lambda p=path, t=text: append_text(p, t))
    first, second = os.path.join(work, "compiler1"), os.path.join(work, "compiler2")
    rebuilds_after(binary, "SAWC command", ["build"], package, lambda: None,
                   blade_environment({"SAWC": fake_compiler(first)}),
                   blade_environment({"SAWC": fake_compiler(second)}))
    versioned = os.path.join(work, "versioned")
    env = blade_environment({"SAWC": fake_compiler(versioned)})
    rebuilds_after(binary, "compiler version", ["build"], package,
                   lambda: set_version(versioned, "sawc 9.0.1"), env)
    for state in ("FAIL", "EMPTY"):
        print("blade: a compiler whose --version is %s is never up to date" % state, flush=True)
        set_version(versioned, state)
        for attempt in (1, 2):
            out = blade_ok(binary, ["build"], package, "Compiling", env)
            if "(up to date)" in out:
                raise Failure("a build with a compiler whose --version is %s was up to date\n%s" % (state, out))
        set_version(versioned, "sawc 9.0.1")
        blade_ok(binary, ["build"], package, "Compiling", env)
        blade_ok(binary, ["build"], package, "(up to date)", env)
    identified = os.path.join(work, "identified")
    env = blade_environment({"SAWC": fake_compiler(identified)})
    set_build_id(identified, "id-1")
    rebuilds_after(binary, "compiler identity", ["build"], package,
                   lambda: set_build_id(identified, "id-2"), env)
    for state in ("FAIL", "EMPTY", "MANY"):
        print("blade: a compiler whose --build-id is %s is never up to date" % state, flush=True)
        set_build_id(identified, state)
        for attempt in (1, 2):
            out = blade_ok(binary, ["build"], package, "Compiling", env)
            if "(up to date)" in out:
                raise Failure("a build with a compiler whose --build-id is %s was up to date\n%s" % (state, out))
        set_build_id(identified, "id-2")
        blade_ok(binary, ["build"], package, "Compiling", env)
        blade_ok(binary, ["build"], package, "(up to date)", env)
    stdcopy = os.path.join(work, "stdcopy")
    env = blade_environment({"SAWC": std_copy_compiler(stdcopy)})
    rebuilds_after(binary, "std the compiler compiles against", ["build"], package,
                   lambda: append_text(os.path.join(stdcopy, "std", "vector.saw"), "\n// edited\n"), env)
    switched = os.path.join(work, "stageswitch")
    env = blade_environment({"SAWC": stage_switch_compiler(switched, build.STAGE2)})
    rebuilds_after(binary, "compiler binary, with the version line unchanged", ["build"], package,
                   lambda: set_stage(switched, build.STAGE1), env)


def check_blade_freshness_images(binary=None):
    """An image build is up to date only while its native units (C and assembly,
    not their headers), `SOS_CLANG`, `SOS_LD` and the tools `sawc tools` records
    for the target are unchanged."""
    binary = binary or SELF_BUILT
    triple = "riscv32-unknown-none-elf"
    if not has_sawc_record(triple):
        print("blade: no sawc record for %s: the freshness of an image build is not checked" % triple, flush=True)
        return
    package, root = image_package()
    args = ["build", "--target", triple]
    unset = blade_environment()
    for name in ("SOS_CLANG", "SOS_LD"):
        unset.pop(name, None)
    rebuilds_after(binary, "native C unit", args, package,
                   lambda: append_text(os.path.join(root, "hal", "support.c"), "// edited\n"), unset)
    rebuilds_after(binary, "native assembly unit", args, package,
                   lambda: append_text(os.path.join(root, "hal", "riscv32", "boot.S"), "// edited\n"), unset)
    with open(os.path.join(os.path.dirname(build.SAWC), "sawc-runtime-%s.txt" % triple), encoding="utf-8") as f:
        recorded = f.read()
    clang = re.search(r"^clang (.+)$", recorded, re.M)
    linker = shutil.which("ld.lld", path=unset.get("PATH"))
    if not clang or not linker:
        raise Failure("the lane found no clang in the sawc record for %s or no ld.lld on PATH" % triple)
    other_clang = os.path.join(root, "other-clang.sh")
    write_script(other_clang, '#!/bin/bash\nexec "%s" "$@"\n' % clang.group(1))
    other_linker = os.path.join(root, "other-ld.sh")
    write_script(other_linker, '#!/bin/bash\nexec "%s" "$@"\n' % linker)
    with_clang = dict(unset)
    with_clang["SOS_CLANG"] = other_clang
    rebuilds_after(binary, "SOS_CLANG", args, package, lambda: None, unset, with_clang)
    with_linker = dict(unset)
    with_linker["SOS_LD"] = other_linker
    rebuilds_after(binary, "SOS_LD", args, package, lambda: None, unset, with_linker)
    compiler = os.path.join(root, "recording")
    env = blade_environment({"SAWC": fake_compiler(compiler)})
    for name in ("SOS_CLANG", "SOS_LD"):
        env.pop(name, None)
    write_script(os.path.join(compiler, "tools.txt"), "clang %s\nobjcopy /unused\n" % clang.group(1))
    rebuilds_after(binary, "clang the target's record names", args, package,
                   lambda: write_script(os.path.join(compiler, "tools.txt"), "clang %s\nobjcopy /unused\n" % other_clang),
                   env)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


HIDDEN_ALLOC_DIAGNOSTIC = "alloc.hidden"
INTERPOLATING_MAIN = 'func main() {\n    let n = 3\n    let s = "n is {n}"\n    print(s)\n}\n'
PLAIN_MAIN = 'func main() {\n    print("plain")\n}\n'


def hidden_alloc_manifest(key):
    """A Saw.toml for a package `app`; `key` is the text of its no-hidden-alloc line, or None."""
    return '[package]\nname = "app"\nversion = "0.1.0"\n%s' % ("no-hidden-alloc = %s\n" % key if key else "")


def check_blade_no_hidden_alloc(binary=None):
    """`[package] no-hidden-alloc = true` has Blade pass `--no-hidden-alloc` to every sawc
    run of a build whose root package declares it: `blade build` refuses an interpolation
    with sawc's diagnostic and `blade test` fails a test program that has one; the same package
    without the key (or with `false`) builds and tests; flipping the key after an
    up-to-date build rebuilds; a dependency's key does not reach its dependents."""
    binary = binary or SELF_BUILT
    work = os.path.join(WORK_DIR, "no_hidden_alloc")
    shutil.rmtree(work, ignore_errors=True)
    package = os.path.join(work, "app")
    manifest = os.path.join(package, "Saw.toml")
    write_text(os.path.join(package, "src", "main.saw"), INTERPOLATING_MAIN)
    write_text(os.path.join(package, "tests", "interp.saw"), INTERPOLATING_MAIN)
    write_text(manifest, hidden_alloc_manifest("true"))
    print("blade: a package with no-hidden-alloc = true is refused for an interpolation", flush=True)
    blade_refused(binary, ["build"], package, HIDDEN_ALLOC_DIAGNOSTIC)
    print("blade: its test program that interpolates fails to compile under blade test", flush=True)
    code, out = run_blade(binary, ["test"], package)
    if code == 0 or "test interp ... FAILED" not in out:
        raise Failure("blade test with no-hidden-alloc = true did not fail the interpolating test (exit %s)\n%s"
                      % (code, out))
    for key in (None, "false"):
        write_text(manifest, hidden_alloc_manifest(key))
        print("blade: the same package with %s builds and tests" % ("no key" if key is None else "no-hidden-alloc = false"),
              flush=True)
        blade_ok(binary, ["build"], package, "Finished .build/host/app")
        blade_ok(binary, ["test"], package, "test result: ok")
    plain = os.path.join(work, "plain")
    write_text(os.path.join(plain, "src", "main.saw"), PLAIN_MAIN)
    write_text(os.path.join(plain, "Saw.toml"), hidden_alloc_manifest(None))
    rebuilds_after(binary, "no-hidden-alloc key, set", ["build"], plain,
                   lambda: write_text(os.path.join(plain, "Saw.toml"), hidden_alloc_manifest("true")))
    rebuilds_after(binary, "no-hidden-alloc key, cleared", ["build"], plain,
                   lambda: write_text(os.path.join(plain, "Saw.toml"), hidden_alloc_manifest("false")))
    wrong = os.path.join(work, "wrong")
    write_text(os.path.join(wrong, "src", "main.saw"), PLAIN_MAIN)
    write_text(os.path.join(wrong, "Saw.toml"), hidden_alloc_manifest('"true"'))
    print("blade: no-hidden-alloc = \"true\" is refused as a string", flush=True)
    blade_refused(binary, ["build"], wrong, "`no-hidden-alloc` in [package] is a string, not a boolean")
    root = os.path.join(work, "root")
    write_text(os.path.join(root, "Saw.toml"),
               '[package]\nname = "root"\nversion = "0.1.0"\n\n[dependencies]\nlib = { path = "../strictlib" }\n')
    write_text(os.path.join(root, "src", "main.saw"), 'import lib\n\nfunc main() {\n    print(lib.shout(2))\n}\n')
    write_text(os.path.join(work, "strictlib", "Saw.toml"),
               '[package]\nname = "lib"\nversion = "0.1.0"\nno-hidden-alloc = true\n')
    write_text(os.path.join(work, "strictlib", "src", "lib.saw"),
               'public func shout(n: Int) -> String {\n    "n is {n}"\n}\n')
    print("blade: a dependency's no-hidden-alloc key does not reach the package that depends on it", flush=True)
    blade_ok(binary, ["build"], root, "Finished .build/host/root")
    write_text(os.path.join(root, "Saw.toml"),
               '[package]\nname = "root"\nversion = "0.1.0"\nno-hidden-alloc = true\n\n[dependencies]\nlib = { path = "../strictlib" }\n')
    print("blade: the root's key makes the dependency's interpolation an error", flush=True)
    blade_refused(binary, ["build"], root, HIDDEN_ALLOC_DIAGNOSTIC)
    check_blade_no_hidden_alloc_image(binary)


def check_blade_no_hidden_alloc_image(binary):
    """The `[sos]` image build passes the flag too: the lane's image package with an
    interpolation in its `main` builds with no key and with `false`, and `true` is
    refused with sawc's diagnostic."""
    triple = "riscv32-unknown-none-elf"
    if not has_sawc_record(triple):
        print("blade: no sawc record for %s: the image build's no-hidden-alloc key is not checked" % triple, flush=True)
        return
    package, _root = image_package()
    env = blade_environment()
    for name in ("SOS_CLANG", "SOS_LD"):
        env.pop(name, None)
    main = os.path.join(package, "src", "main.saw")
    with open(main, encoding="utf-8") as f:
        source = f.read()
    marker = '    print("fs: hello from a Blade-built image")\n'
    if marker not in source:
        raise Failure("%s no longer holds the line the no-hidden-alloc image row extends" % main)
    write_text(main, source.replace(marker, marker + '    let n = 7\n    print("n is {n}")\n', 1))
    manifest = os.path.join(package, "Saw.toml")
    with open(manifest, encoding="utf-8") as f:
        original = f.read()
    args = ["build", "--target", triple]
    for key in (None, "false"):
        write_text(manifest, original if key is None else original.replace(
            'version = "0.1.0"\n', 'version = "0.1.0"\nno-hidden-alloc = false\n', 1))
        print("blade: an image with %s builds" % ("no key" if key is None else "no-hidden-alloc = false"), flush=True)
        blade_ok(binary, args, package, "Finished", env)
    write_text(manifest, original.replace('version = "0.1.0"\n', 'version = "0.1.0"\nno-hidden-alloc = true\n', 1))
    print("blade: an image with no-hidden-alloc = true is refused for an interpolation", flush=True)
    blade_refused(binary, args, package, HIDDEN_ALLOC_DIAGNOSTIC, env)


TASK_FRAME_DIAGNOSTIC = "task.frame-size"
BIG_TASK_SOURCE = ("import std.task.*\n\nfunc hold() {\n    var a = [0u8; 70_000]\n    yield_now()\n    a[0] = 1\n}\n\n"
                   "func %s {\n    let t = Task.spawn(hold())\n    t.join()\n}\n")


def task_frame_manifest(key, extra=""):
    """A Saw.toml for a package `app`; `key` is the text of its max-task-frame value, or None."""
    return '[package]\nname = "app"\nversion = "0.1.0"\n%s%s' % ("max-task-frame = %s\n" % key if key else "", extra)


def check_blade_max_task_frame(binary=None):
    """`[package] max-task-frame = "64KiB"` has Blade pass `--max-task-frame=64KiB` to every
    sawc run of a build whose root package declares it: a task whose 70 KB frame the hosted
    default accepts is refused by `blade build` and fails to compile under `blade test`, the
    same package with a larger key builds, flipping the key after an up-to-date build rebuilds,
    a spelling or a type that is not a size is refused naming the key, and a dependency's key
    does not reach its dependents."""
    binary = binary or SELF_BUILT
    work = os.path.join(WORK_DIR, "max_task_frame")
    shutil.rmtree(work, ignore_errors=True)
    package = os.path.join(work, "app")
    manifest = os.path.join(package, "Saw.toml")
    write_text(os.path.join(package, "src", "main.saw"), BIG_TASK_SOURCE % "main()")
    write_text(os.path.join(package, "tests", "big.saw"), BIG_TASK_SOURCE % "main()")
    write_text(manifest, task_frame_manifest('"64KiB"'))
    print('blade: a package with max-task-frame = "64KiB" is refused for a 70 KB task frame', flush=True)
    blade_refused(binary, ["build"], package, TASK_FRAME_DIAGNOSTIC)
    print("blade: its test program with the same task fails to compile under blade test", flush=True)
    code, out = run_blade(binary, ["test"], package)
    if code == 0 or "test big ... FAILED" not in out:
        raise Failure("blade test with max-task-frame = \"64KiB\" did not fail the big task's test (exit %s)\n%s"
                      % (code, out))
    for key in (None, '"128KiB"', "\"1MiB\""):
        write_text(manifest, task_frame_manifest(key))
        print("blade: the same package with %s builds and tests" % ("no key" if key is None else "max-task-frame = " + key),
              flush=True)
        blade_ok(binary, ["build"], package, "Finished .build/host/app")
        blade_ok(binary, ["test"], package, "test result: ok")
    plain = os.path.join(work, "plain")
    write_text(os.path.join(plain, "src", "main.saw"), PLAIN_MAIN)
    write_text(os.path.join(plain, "Saw.toml"), task_frame_manifest(None))
    rebuilds_after(binary, "max-task-frame key, set", ["build"], plain,
                   lambda: write_text(os.path.join(plain, "Saw.toml"), task_frame_manifest('"64KiB"')))
    rebuilds_after(binary, "max-task-frame key, changed", ["build"], plain,
                   lambda: write_text(os.path.join(plain, "Saw.toml"), task_frame_manifest('"96KiB"')))
    for key, said in (('64', "`max-task-frame` in [package] is an integer, not a string"),
                      ('"64 KiB"', "`max-task-frame` in [package] is \"64 KiB\", which is not a size"),
                      ('"64KB"', "which is not a size"),
                      ('""', "which is not a size"),
                      ('"64KiB; echo"', "which is not a size")):
        wrong = os.path.join(work, "wrong")
        write_text(os.path.join(wrong, "src", "main.saw"), PLAIN_MAIN)
        write_text(os.path.join(wrong, "Saw.toml"), task_frame_manifest(key))
        print("blade: max-task-frame = %s is refused" % key, flush=True)
        blade_refused(binary, ["build"], wrong, said)
    zero = os.path.join(work, "zero")
    write_text(os.path.join(zero, "src", "main.saw"), PLAIN_MAIN)
    write_text(os.path.join(zero, "Saw.toml"), task_frame_manifest('"0"'))
    print('blade: max-task-frame = "0" is refused by sawc, which judges the size', flush=True)
    blade_refused(binary, ["build"], zero, "--max-task-frame")
    root = os.path.join(work, "root")
    write_text(os.path.join(root, "Saw.toml"),
               '[package]\nname = "root"\nversion = "0.1.0"\n\n[dependencies]\nlib = { path = "../biglib" }\n')
    write_text(os.path.join(root, "src", "main.saw"), 'import lib\n\nfunc main() {\n    lib.run()\n}\n')
    write_text(os.path.join(work, "biglib", "Saw.toml"),
               '[package]\nname = "lib"\nversion = "0.1.0"\nmax-task-frame = "1KiB"\n')
    write_text(os.path.join(work, "biglib", "src", "lib.saw"), BIG_TASK_SOURCE.replace("func %s", "public func %s") % "run()")
    print("blade: a dependency's max-task-frame key does not reach the package that depends on it", flush=True)
    blade_ok(binary, ["build"], root, "Finished .build/host/root")
    write_text(os.path.join(root, "Saw.toml"),
               '[package]\nname = "root"\nversion = "0.1.0"\nmax-task-frame = "1KiB"\n\n'
               '[dependencies]\nlib = { path = "../biglib" }\n')
    print("blade: the root's key makes the dependency's task frame an error", flush=True)
    blade_refused(binary, ["build"], root, TASK_FRAME_DIAGNOSTIC)


def manifest_app(work, deps):
    """`work/app`, a package whose Saw.toml states `deps` under [dependencies]."""
    package = os.path.join(work, "app")
    write_text(os.path.join(package, "Saw.toml"),
               '[package]\nname = "app"\nversion = "0.1.0"\n\n[dependencies]\n%s\n' % deps)
    write_text(os.path.join(package, "src", "main.saw"), "func main() {\n    print(1)\n}\n")
    return package


def manifest_library(directory, manifest):
    write_text(os.path.join(directory, "Saw.toml"), manifest)
    write_text(os.path.join(directory, "src", "lib.saw"), "public func one() -> Int {\n    1\n}\n")


def check_blade_lock_quoting(binary=None):
    """A dependency whose path holds a backslash or a double quote, or whose key
    needs quotes, resolves, is locked and builds twice (the second one up to
    date). The directories are made here: a name with a backslash or a quote is
    legal on macOS and Linux and is no tracked fixture path."""
    binary = binary or SELF_BUILT
    rows = (
        ("backslash", "l\\ib", 'lib = { path = "../l\\\\ib" }'),
        ("quote", 'l"ib', 'lib = { path = "../l\\"ib" }'),
        ("key", "mylib", '"my lib" = { path = "../mylib" }'),
    )
    for name, directory, declaration in rows:
        work = os.path.join(WORK_DIR, "lock_quoting", name)
        shutil.rmtree(work, ignore_errors=True)
        package = manifest_app(work, declaration)
        manifest_library(os.path.join(work, directory), '[package]\nname = "lib"\nversion = "0.1.0"\n')
        print("blade: a dependency with %s resolves, locks and builds twice" % {
            "backslash": "a backslash in its path", "quote": "a double quote in its path",
            "key": "a key that needs quotes"}[name], flush=True)
        blade_ok(binary, ["update"], package, "Updated Saw.lock")
        blade_ok(binary, ["build"], package, "Finished .build/host/app")
        blade_ok(binary, ["build"], package, "(up to date)")


def check_blade_resolver_says_why(binary=None):
    """A manifest the resolver cannot read is refused with the manifest's own
    text (its path, line, column and reason) by `blade build` and `blade tree`;
    a missing one says so."""
    binary = binary or SELF_BUILT
    junk = '[package]\nname = "lib"\nversion = "0.1.0" junk\n'
    rows = (
        ("a dependency's manifest", 'lib = { path = "../lib" }', junk,
         "cannot read manifest for `lib`: %s: line 3, column 19: expected the end of the line after the value, found `junk`",
         "lib"),
        ("a dependency's own dependencies", 'lib = { path = "../lib" }',
         '[package]\nname = "lib"\nversion = "0.1.0"\n\n[dependencies]\ninner = { path = 7 }\n',
         "cannot read dependencies of `lib`: %s: line 6, column 18: `path` in the inline table `dependencies.inner` is an integer, not a string",
         "lib"),
        ("the root's table", "lib = { path = 5 }", None,
         "cannot read root dependencies: %s: line 6, column 16: `path` in the inline table `dependencies.lib` is an integer, not a string",
         "app"),
        ("a missing manifest", 'lib = { path = "../lib" }', False,
         "cannot read manifest for `lib`: Saw.toml not found in %s", "lib"),
    )
    for index, (title, declaration, library, text, owner) in enumerate(rows):
        work = os.path.join(WORK_DIR, "resolver_says_why", str(index))
        shutil.rmtree(work, ignore_errors=True)
        package = manifest_app(work, declaration)
        if library is False:
            os.makedirs(os.path.join(work, "lib"))
        elif library is not None:
            manifest_library(os.path.join(work, "lib"), library)
        place = os.path.join(work, owner) if owner == "lib" else package
        expected = text % (place if library is False else os.path.join(place, "Saw.toml"))
        print("blade: %s is refused with its reason" % title, flush=True)
        blade_refused(binary, ["build"], package, "dependency resolution failed: " + expected)
        blade_refused(binary, ["tree"], package, "error: " + expected)


def sawc_clang_and_triple():
    """(clang, triple) from `sawc tools`: the compiler sawc links with and the triple it compiles
    the host's modules for, or None when it names no clang."""
    code, out = run([build.SAWC, "tools"], SMOKE_TIMEOUT_S)
    clang = re.search(r"^clang (.+)$", out, re.M)
    triple = re.search(r"^triple (.+)$", out, re.M)
    if code != 0 or not clang or not triple:
        return None
    return clang.group(1), triple.group(1)


def sawc_host_target():
    """The target name the runtime record beside `build.SAWC` is for, or None."""
    try:
        with open(os.path.join(os.path.dirname(build.SAWC), "sawc-runtime.txt"), encoding="utf-8") as f:
            found = re.search(r"^target (.+)$", f.read(), re.M)
    except OSError:
        return None
    return found.group(1) if found else None


NATIVE_OTHER_TARGET = "riscv32-unknown-none-elf"


def make_c_object(clang, triple, directory, name, function, value, archive=None):
    """Compile `int FUNCTION(void) { return VALUE; }` to `directory/NAME.o` for `triple`, and, given an
    `archive` name, put it into `directory/ARCHIVE` (an `ar` archive) in its place."""
    source = os.path.join(directory, name + ".c")
    write_text(source, "int %s(void) { return %d; }\n" % (function, value))
    obj = os.path.join(directory, name + ".o")
    code, out = run([clang, "-target", triple, "-O1", "-c", source, "-o", obj], SMOKE_TIMEOUT_S)
    if code != 0:
        raise Failure("clang did not compile %s\n%s" % (source, out))
    os.remove(source)
    if archive:
        path = os.path.join(directory, archive)
        if os.path.exists(path):
            os.remove(path)
        code, out = run([shutil.which("ar"), "rcs", path, obj], SMOKE_TIMEOUT_S)
        if code != 0:
            raise Failure("ar did not make %s\n%s" % (path, out))
        os.remove(obj)


NATIVE_LIBRARY_SOURCE = (
    'extern "C" {\n    func lib_obj_value() -> Int32\n    func lib_arc_value() -> Int32\n'
    '    func lib_pl_value() -> Int32\n}\n\n'
    'public func answer() -> Int {\n    (lib_obj_value() + lib_arc_value()) as Int\n}\n\n'
    'public func named() -> Int {\n    lib_pl_value() as Int\n}\n')


def check_blade_native(binary=None):
    """A package's `[native]` prebuilt inputs reach the link of `blade build`, `blade run` and
    `blade test`, through a path dependency whose directory holds a space and double quotes: an
    object found by a pattern, an archive in a table of the host's triple, and a library found
    through a library directory build and run, a table of another triple is left alone, an
    unchanged second build is up to date, and rewriting the object or the archive rebuilds
    (the contents of a library named with `libraries` are not tracked).
    A manifest `[native]` cannot honour, and a file it names that is not there, is refused."""
    binary = binary or SELF_BUILT
    tools = sawc_clang_and_triple()
    host = sawc_host_target()
    if tools is None or host is None or shutil.which("ar") is None:
        print("blade: no clang from `sawc tools`, host record or `ar`: prebuilt `[native]` inputs are not checked",
              flush=True)
        return
    clang, triple = tools
    work = os.path.join(WORK_DIR, "native")
    shutil.rmtree(work, ignore_errors=True)
    library = os.path.join(work, 'lib "dir"')
    app = os.path.join(work, "app")
    make_c_object(clang, triple, os.path.join(library, "prebuilt"), "obj", "lib_obj_value", 40)
    make_c_object(clang, triple, os.path.join(library, "archives"), "arc", "lib_arc_value", 2, "libarc.a")
    make_c_object(clang, triple, os.path.join(library, "libpath"), "pl", "lib_pl_value", 1000, "libpl.a")
    write_text(os.path.join(library, "Saw.toml"),
               '[package]\nname = "clib"\nversion = "0.1.0"\n\n[native]\nobjects = ["prebuilt/*.o"]\n'
               'libraries = ["pl"]\nlibrary-paths = ["libpath"]\n\n'
               '[native.%s]\narchives = ["archives/libarc.a"]\n\n[native.%s]\nobjects = ["not/there.o"]\n'
               % (host, NATIVE_OTHER_TARGET))
    write_text(os.path.join(library, "src", "lib.saw"), NATIVE_LIBRARY_SOURCE)
    write_text(os.path.join(app, "Saw.toml"),
               '[package]\nname = "app"\nversion = "0.1.0"\n\n[dependencies]\nclib = { path = "../lib \\"dir\\"" }\n')
    write_text(os.path.join(app, "src", "main.saw"),
               'import clib\n\nfunc main() {\n    print("answer {clib.answer()} named {clib.named()}")\n}\n')
    write_text(os.path.join(app, "tests", "answer.saw"),
               'import clib\n\nfunc main() {\n    assert(clib.answer() == 42, "the object and the archive")\n'
               '    assert(clib.named() == 1000, "the library")\n}\n')
    print("blade: a dependency's prebuilt object, archive and library build, run and test", flush=True)
    blade_ok(binary, ["build"], app, "Finished .build/host/app")
    blade_ok(binary, ["build"], app, "(up to date)")
    blade_ok(binary, ["run"], app, "answer 42 named 1000")
    blade_ok(binary, ["test"], app, "test result: ok")
    rebuilds_after(binary, "prebuilt object", ["build"], app,
                   lambda: make_c_object(clang, triple, os.path.join(library, "prebuilt"), "obj", "lib_obj_value", 41))
    blade_ok(binary, ["run"], app, "answer 43 named 1000")
    rebuilds_after(binary, "archive", ["build"], app,
                   lambda: make_c_object(clang, triple, os.path.join(library, "archives"), "arc", "lib_arc_value", 3,
                                         "libarc.a"))
    blade_ok(binary, ["run"], app, "answer 44 named 1000")
    print("blade: a library found by name is not hashed: its change leaves the build up to date", flush=True)
    make_c_object(clang, triple, os.path.join(library, "libpath"), "pl", "lib_pl_value", 7, "libpl.a")
    blade_ok(binary, ["build"], app, "(up to date)")
    refusals = (
        ("an unknown key", '[native]\nsources = ["a.c"]\n', "[native] has an unknown key `sources`"),
        ("a target the compiler does not know", '[native.not-a-triple]\nobjects = ["a.o"]\n',
         "`not-a-triple` is not a target the compiler knows"),
        ("a pattern that matches nothing", '[native]\nobjects = ["none/*.o"]\n', "`none/*.o` matches no file"),
        ("a framework outside a Mach-O triple's table", '[native]\nframeworks = ["Security"]\n',
         "belongs in the [native.<triple>] table of an `-apple-` triple"),
        ("a function-like define", '[native]\ndefines = ["SQUARE(x)=((x)*(x))"]\n', "function-like macro"),
        ("a missing object", '[native]\nobjects = ["gone.o"]\n', "`gone.o` does not exist"),
    )
    for index, (title, native, said) in enumerate(refusals):
        package = os.path.join(work, "refused%d" % index)
        write_text(os.path.join(package, "Saw.toml"), '[package]\nname = "refused"\nversion = "0.1.0"\n\n' + native)
        write_text(os.path.join(package, "src", "main.saw"), PLAIN_MAIN)
        write_text(os.path.join(package, "tests", "plain.saw"), PLAIN_MAIN)
        print("blade: [native] with %s is refused" % title, flush=True)
        blade_refused(binary, ["build"], package, said)
    print("blade: blade test refuses a `[native]` input that is not there", flush=True)
    blade_refused(binary, ["test"], os.path.join(work, "refused5"), "`gone.o` does not exist")


NATIVE_C_SOURCES = {
    "a": '#include "config.h"\nint c_a(void) { return BASE + LEVEL; }\n',
    "b": "int c_b(void) {\n#ifdef FLAG\n    return 7;\n#else\n    return 0;\n#endif\n}\n",
    "c": "int c_c(void) { return 9; }\n",
}
NATIVE_C_BROKEN_B = "int c_b(void) { return ; }\n"
NATIVE_C_LIBRARY_SOURCE = (
    'extern "C" {\n    func c_a() -> Int32\n    func c_b() -> Int32\n    func c_c() -> Int32\n}\n\n'
    'public func total() -> Int {\n    (c_a() + c_b() + c_c()) as Int\n}\n')


def native_c_objects(package, library):
    """The objects Blade compiled for `library` under `package`'s build directory, by source stem."""
    directory = os.path.join(package, ".build", "host", "native", library)
    found = {}
    for name in sorted(os.listdir(directory)):
        if name.endswith(".o"):
            found[name.split("-", 1)[1][:-2]] = os.path.join(directory, name)
    return found


def native_c_state(objects):
    """(object mtime in ns, key text) per stem, which a rebuild of one object moves for that object alone."""
    state = {}
    for stem, path in objects.items():
        with open(path + ".key", encoding="utf-8") as f:
            state[stem] = (os.stat(path).st_mtime_ns, f.read())
    return state


def check_blade_native_c(binary=None):
    """A dependency's `[native]` C sources, found by a pattern in a directory whose name holds a space and
    double quotes, compile with its include directory and defines, link into `blade build`, `blade run` and
    `blade test`, and are cached: an unchanged build is up to date, a header edit recompiles the one object
    that includes it (the other objects, and their keys, stay), and a syntax error in one of three sources
    fails the build with that source's diagnostic printed once and the others' left out."""
    binary = binary or SELF_BUILT
    work = os.path.join(WORK_DIR, "native_c")
    shutil.rmtree(work, ignore_errors=True)
    library = os.path.join(work, 'lib "dir"')
    app = os.path.join(work, "app")
    write_text(os.path.join(library, "Saw.toml"),
               '[package]\nname = "clib"\nversion = "0.1.0"\n\n[native]\nc-sources = ["c/*.c"]\n'
               'include-dirs = ["inc"]\ndefines = ["LEVEL=5", "FLAG"]\n')
    write_text(os.path.join(library, "inc", "config.h"), "#define BASE 100\n")
    for stem, text in NATIVE_C_SOURCES.items():
        write_text(os.path.join(library, "c", stem + ".c"), text)
    write_text(os.path.join(library, "src", "lib.saw"), NATIVE_C_LIBRARY_SOURCE)
    write_text(os.path.join(app, "Saw.toml"),
               '[package]\nname = "app"\nversion = "0.1.0"\n\n[dependencies]\nclib = { path = "../lib \\"dir\\"" }\n')
    write_text(os.path.join(app, "src", "main.saw"),
               'import clib\n\nfunc main() {\n    print("total {clib.total()}")\n}\n')
    write_text(os.path.join(app, "tests", "total.saw"),
               'import clib\n\nfunc main() {\n    assert(clib.total() == 121, "the three C sources")\n}\n')
    print("blade: a dependency's C sources compile, link, run and test", flush=True)
    blade_ok(binary, ["build"], app, "Finished .build/host/app")
    blade_ok(binary, ["build"], app, "(up to date)")
    blade_ok(binary, ["run"], app, "total 121")
    blade_ok(binary, ["test"], app, "test result: ok")
    objects = native_c_objects(app, "clib")
    if sorted(objects) != ["a", "b", "c"]:
        raise Failure("the three sources have objects %s" % sorted(objects))
    before = native_c_state(objects)

    print("blade: a header edit recompiles only the object that includes it", flush=True)
    write_text(os.path.join(library, "inc", "config.h"), "#define BASE 200\n")
    out = blade_ok(binary, ["build"], app, "Compiling")
    if "(up to date)" in out or "c/a.c" not in out or "c/b.c" in out or "c/c.c" in out:
        raise Failure("a header only a.c includes should recompile a.c alone\n%s" % out)
    blade_ok(binary, ["run"], app, "total 221")
    after = native_c_state(objects)
    if after["a"] == before["a"] or after["a"][1] == before["a"][1]:
        raise Failure("the object that includes the header was not recompiled")
    for stem in ("b", "c"):
        if after[stem] != before[stem]:
            raise Failure("the object of %s.c changed with a header it does not include" % stem)
    blade_ok(binary, ["build"], app, "(up to date)")

    print("blade: a define edit recompiles every object", flush=True)
    write_text(os.path.join(library, "Saw.toml"),
               '[package]\nname = "clib"\nversion = "0.1.0"\n\n[native]\nc-sources = ["c/*.c"]\n'
               'include-dirs = ["inc"]\ndefines = ["LEVEL=6", "FLAG"]\n')
    blade_ok(binary, ["run"], app, "total 222")
    redone = native_c_state(objects)
    if any(redone[stem][1] == after[stem][1] for stem in redone):
        raise Failure("a changed define should change every object's key")

    print("blade: a syntax error in one of three sources fails the build with its diagnostic once", flush=True)
    write_text(os.path.join(library, "c", "b.c"), NATIVE_C_BROKEN_B)
    code, out = run_blade(binary, ["build"], app)
    if code == 0:
        raise Failure("a syntax error in b.c did not fail the build\n%s" % out)
    if out.count("error: compiling") != 1 or "b.c" not in out or out.count("should return a value") != 1:
        raise Failure("the failure should print b.c's diagnostic once\n%s" % out)
    if "a.c" in out or "c/c.c" in out:
        raise Failure("the sources that compile should print nothing\n%s" % out)
    write_text(os.path.join(library, "c", "b.c"), NATIVE_C_SOURCES["b"])
    blade_ok(binary, ["run"], app, "total 222")


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
        check_blade_tree_status()
        check_blade_module_path()
        check_blade_lock_quoting()
        check_blade_resolver_says_why()
        check_blade_out_dir_and_linker_script()
        check_blade_out_dir_names_target()
        check_blade_image_module_path()
        check_blade_freshness_hosted()
        check_blade_freshness_images()
        check_blade_no_hidden_alloc()
        check_blade_max_task_frame()
        check_blade_native()
        check_blade_native_c()
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
