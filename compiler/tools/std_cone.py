#!/usr/bin/env python3
"""The std cone of a program: every declaration of the new std it reaches.

    python compiler/tools/std_cone.py --entry FILE [--std-root DIR]

The cone is read off sawc2's own typecheck dump of the program against the
new std (`new_std_cone`); the std lane holds the recorded cones in
`compiler/tests/std/cone/`, sawc2's own among them (`sawc2.cone`).
"""
import argparse
import difflib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import build  # noqa: E402

TIMEOUT = 600


def diff_lines(expected, got):
    """(added, removed): the lines a positional diff changes, each naming the
    declaration it sits under, since an instance line repeats under many."""
    exp, new = expected.splitlines(), got.splitlines()
    added, removed = [], []
    matcher = difflib.SequenceMatcher(None, exp, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += [_line_under(exp, i) for i in range(i1, i2)]
        if tag in ("replace", "insert"):
            added += [_line_under(new, j) for j in range(j1, j2)]
    return added, removed


def _line_under(lines, i):
    """Line `i`, with the nearest line above it that is indented less."""
    line = lines[i]
    depth = len(line) - len(line.lstrip())
    k = i - 1
    while k >= 0 and depth > 0:
        above = lines[k]
        if above.strip() and len(above) - len(above.lstrip()) < depth:
            return "%s (under %s)" % (line.strip(), above.strip())
        k -= 1
    return line.strip()


# ------------------------------------------------------- the new std's cone
# The cone is read off sawc2's own typecheck dump: every std declaration a
# program's functions reach through their calls, the types their bodies name
# and the lang item each String position in them lowers through, closed over
# each reached type's `deinit` and `copy` and each reached requirement's
# implementations. The panic sink is always in it, since any body may panic.

_NEW_DECL = re.compile(r"^    \((\w[\w-]*) ([^ ]+) \d+:\d+")
_NEW_BODY = re.compile(r"^    \(([^ ]+) \d+:\d+$")
_NEW_CALL = re.compile(r"\((?:call|memberwise|iterator) ([\w.]+)")
_NEW_NAME = re.compile(r"[A-Za-z_][\w.]*")
_NEW_CONFORMANCE = re.compile(r"^    \(([\w.]+) ([\w.]+) \d+:\d+((?: \(\w+ \w+\))*)\)*$")
_NEW_LANG = re.compile(r"^    \((\w+) ([\w.]+)\)")
# A position names one lang item, or several where the compiler reads more
# than one (a String argument's bytes and length).
_NEW_POSITION = re.compile(r"^    \((\d+:\d+) ([\w-]+) ([\w. ]+)\)")
_NEW_LINE_START = re.compile(r"^\s*\((\d+:\d+)-")
# What a String position reaches of its lang item, when not the item itself:
# an interpolation builds, appends and finishes; a format string's scratch is
# built and appended to; a Printable message renders through `to_string`.
_POSITION_MEMBERS = {
    "interpolation": ("", ".init", ".append", ".build"),
    "format": ("", ".init", ".append"),
    "rendered": (".to_string",),
}


def _new_std_dump(entry, std_root, extra=()):
    args = ["--std-root", std_root] + list(extra) + [entry]
    r = subprocess.run([build.SAWC2, "typecheck", "--dump"] + args,
                       cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    problems = [l for l in r.stdout.splitlines() if l.startswith(("ERROR", "INVARIANT"))]
    lang = subprocess.run([build.SAWC2, "resolve", "--dump"] + args,
                          cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    return r.stdout, lang.stdout, problems


def new_std_cone(entry, std_root="std", extra=()):
    """(text, problems, reached) for `entry` against the new std at `std_root`,
    `extra` the sawc2 arguments it also needs (its `--module-path`s): the cone
    as `module: count` blocks of `kind name` lines.

    A reached trait requirement reaches each written implementor whose self
    type the cone also reaches. That is sound because a dispatch reaches an
    implementation only through a value of its type, and an `any Trait` value
    is made at a conversion site whose concrete type the cone already holds. An
    implementor on a type the dump declares nowhere (`String`, a range) is kept
    unconditionally, since its reach is not tracked."""
    dump, resolved, problems = _new_std_dump(entry, std_root, extra)
    if problems:
        return None, ["new std cone: %s" % p for p in problems], None
    decls = {}        # identity -> kind
    bodies = {}       # identity -> body text
    bare = {}         # a vocabulary module's bare name -> identity
    implementors = {}  # (trait identity, requirement) -> [method identity]
    # (module, L:C) -> the lang items a String position there lowers through:
    # what the compiler synthesizes at a literal, an interpolation or a
    # message is reached from the body that holds it.
    positions = {}
    body_module = {}   # body identity -> its module
    module = None
    section = None
    current = None
    for line in dump.splitlines():
        if line.startswith("(Module "):
            module, section, current = line[len("(Module "):].strip(), None, None
            continue
        if line.startswith("  (") and module:
            section = line.strip("( )\n").split(" ")[0]
            continue
        if section == "declarations":
            m = _NEW_DECL.match(line)
            if m and m.group(1) != "extension":
                identity = "%s.%s" % (module, m.group(2))
                decls[identity] = m.group(1)
                if module in ("builtin", "std.prelude"):
                    bare[m.group(2)] = identity
        elif section == "conformances":
            m = _NEW_CONFORMANCE.match(line)
            if m:
                owner, trait = m.group(1), m.group(2)
                for req in re.findall(r"\((\w+) written\)", m.group(3)):
                    implementors.setdefault((trait, req), []).append("%s.%s" % (owner, req))
        elif section == "bodies":
            m = _NEW_BODY.match(line)
            if m:
                current = "%s.%s" % (module, m.group(1))
                # Overloads share an identity, so their bodies are one.
                bodies.setdefault(current, [])
                body_module[current] = module
            elif current is not None:
                bodies[current].append(line)
        elif section == "string-positions":
            m = _NEW_POSITION.match(line)
            if m:
                roles = [item + member for item in m.group(3).split(" ")
                         for member in _POSITION_MEMBERS.get(m.group(2), ("",))]
                positions.setdefault((module, m.group(1)), []).extend(roles)

    def identity_of(name):
        if name in decls:
            return name
        return bare.get(name)

    seeds = [d for d, kind in decls.items() if kind in ("func", "method", "init")
             and not d.startswith(("std.", "builtin."))]
    optional = None
    for line in resolved.splitlines():
        m = _NEW_LANG.match(line)
        if m and m.group(1) == "panic_sink":
            seeds.append(m.group(2))
        elif m and m.group(1) == "Optional":
            optional = m.group(2)
    reached, work = set(), list(seeds)
    # A reached requirement's implementors on a declared type whose type is not
    # reached yet, by that type: they join the cone when it does.
    waiting = {}
    while work:
        d = work.pop()
        if d is None or d in reached:
            continue
        reached.add(d)
        for line in bodies.get(d, ()):
            for target in _NEW_CALL.findall(line):
                work.append(identity_of(target))
            start = _NEW_LINE_START.match(line)
            if start:
                for role in positions.get((body_module[d], start.group(1)), ()):
                    work.append(identity_of(role))
            # `T?` spells the Optional lang item with no name to find.
            if "?" in line:
                work.append(optional)
            for name in _NEW_NAME.findall(line.strip().split(" ", 2)[-1]):
                found = identity_of(name)
                if found is not None and decls.get(found) in ("struct", "enum"):
                    work.append(found)
        kind = decls.get(d)
        if kind in ("struct", "enum"):
            # A copy hook runs where a transfer copies, as a deinit runs where
            # a value drops, with no call written.
            work.append(identity_of(d + ".deinit"))
            work.append(identity_of(d + ".copy"))
            work += waiting.pop(d, [])
        if kind == "requirement":
            trait, req = d.rsplit(".", 1)
            short = trait.split(".")[-1] if trait.startswith("std.prelude.") else trait
            for impl in implementors.get((short, req), []) + implementors.get((trait, req), []):
                owner = impl.rsplit(".", 1)[0]
                if decls.get(owner) in ("struct", "enum") and owner not in reached:
                    waiting.setdefault(owner, []).append(identity_of(impl))
                else:
                    work.append(identity_of(impl))
    by_module = {}
    for d in reached:
        if d.startswith(("std.", "builtin.")) and d in decls:
            owner = _module_of_identity(d)
            by_module.setdefault(owner, []).append("  %s %s" % (decls[d], d[len(owner) + 1:]))
    lines = ["# The cone of %s against the new std (%s): every std declaration its"
             % (os.path.relpath(entry, REPO), std_root),
             "# functions reach, read off sawc2's typecheck dump by compiler/tools/std_cone.py.",
             "# %d declarations in %d modules" % (sum(len(v) for v in by_module.values()),
                                                  len(by_module)), ""]
    for mod in sorted(by_module):
        lines.append("%s: %d" % (mod, len(by_module[mod])))
        lines += sorted(by_module[mod])
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n", [], reached


def _module_of_identity(identity):
    """The module part of a std declaration identity: `builtin`, or `std.X`."""
    parts = identity.split(".")
    return parts[0] if parts[0] == "builtin" else ".".join(parts[:2])


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--entry", metavar="FILE", required=True, help="the program whose cone to print")
    ap.add_argument("--std-root", metavar="DIR", default="std",
                    help="the new std to read the cone against")
    args = ap.parse_args(argv)
    text, problems, _ = new_std_cone(os.path.abspath(args.entry), args.std_root)
    for p in problems:
        print(p)
    sys.stdout.write(text or "")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
