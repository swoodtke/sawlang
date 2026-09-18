#!/usr/bin/env python3
"""`type_identity.module_tag` is INJECTIVE over module paths (SL-274 review r2).

Every `$m$`/`$M$` tag the compiler spells comes out of that one function, so two
modules rendering alike means two declarations taking one LLVM symbol — which
surfaces as `internal compiler error: <symbol>` at the second definition, with
nothing pointing at the modules that collided. It happened twice in one review:
the entry module rendered as the word `root` (r1), and then `"_".join(parts)`
rendered `("a", "b")` and `("a_b",)` alike (r2, codex's program below):

    module a_b { func helper(n: Int) -> Int { n + 100 } ... }
    module a { public module b { public func helper(n: Int) -> Int { n + 200 } } }
    -> internal compiler error: helper$m$a_b

Both were docstring claims nothing checked. This is the check: the pinned
renderings that keep the everyday tags stable, and — over a generated grid of
paths that exercises every escape position — that no two modules share a tag,
that a tag stays inside `[A-Za-z0-9_]` (what `ErrorReporter._QUALIFIER_RE`
scrubs and what LLVM takes unquoted), and that a DECODER written from the
docstring's rule recovers the exact path. The decoder lives here rather than in
`sawc/`: nothing in the compiler reads a tag back, and an inverse that is
never wrong is the proof the encoding loses nothing.

The `.saw` regressions for the two collisions above are
`examples/module_named_root_is_not_the_entry_module.saw` and
`examples/flat_and_nested_module_paths_are_distinct.saw`; this is the property
behind them.

Run standalone or through `tools/battery.sh` (the `moduletag` stage).
"""

import itertools
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sawc"))

from type_identity import module_tag  # noqa: E402

# The renderings the rest of the compiler, its tests and its prose name. A
# change here is a change to every symbol a program of that shape emits.
PINNED = [
    ((), ""),                                          # the entry module
    (("dep",), "dep"),
    (("a", "b"), "a_b"),
    (("a_b",), "a_0b"),                                # not `("a", "b")`
    (("root",), "root"),                               # not the entry module
    (("modules", "d144_pub_a"), "modules_d144_0pub_0a"),
    (("<std>", "once"), "std_once"),                   # `State$m$std_once`
    (("<std>", "data"), "std_data"),
    (("<std>", "compiler.frame"), "std_compiler_frame"),
    (("std", "once"), "_173_td_once"),                 # a USER module `std.once`
    (("std",), "_173_td"),
    (("café",), "caf_1e9_"),                      # a non-ASCII identifier
    (("0start",), "_130_start"),                       # a leading marker digit
    (("_lead",), "_0lead"),
]

# Components that reach every branch of the escape: plain, underscore-bearing at
# each position, all-underscore, already-escaped-looking, leading marker digits,
# the reserved std head, a dotted std leaf, and a non-ASCII identifier.
ATOMS = ["a", "b", "a_b", "_a", "a_", "__", "_", "ab", "a_0b", "0a", "1a",
         "a0", "std", "once", "café", "a.b", "_173_td"]
STD_LEAVES = ["once", "compiler.frame", "a_b", "a.b", "a", "b", "std"]


def decode(tag):
    """The inverse `module_tag`'s docstring describes, written out.

    A `_` followed by `0` is a literal underscore; a `_` followed by `1` opens a
    `_1<hex>_` character escape whose digits run to the next `_`; any other `_`
    ends a component. Returns the component tuple, with the std head spelled
    `std` (it is a component like any other once rendered)."""
    if tag == "":
        return ()
    comps, cur, i = [], [], 0
    while i < len(tag):
        ch = tag[i]
        if ch != "_":
            cur.append(ch)
            i += 1
            continue
        nxt = tag[i + 1] if i + 1 < len(tag) else None
        if nxt == "0":
            cur.append("_")
            i += 2
        elif nxt == "1":
            end = tag.index("_", i + 2)
            cur.append(chr(int(tag[i + 2:end], 16)))
            i = end + 1
        else:
            comps.append("".join(cur))
            cur = []
            i += 1
    comps.append("".join(cur))
    return tuple(comps)


def components(module):
    """The components a tag must decode to: the path itself, with a std module's
    `("<std>", leaf)` head spelled `std` and its dotted leaf split apart."""
    if module[:1] == ("<std>",):
        out = ["std"]
        for seg in module[1:]:
            out.extend(seg.split("."))
        return tuple(out)
    return tuple(module)


def identity(module):
    """WHICH MODULE this path is. `("<std>", "a.b")` and `("<std>", "a", "b")`
    are one module written two ways (the leaf's dots ARE path separators), so
    they are allowed — required — to render alike; a std module and a user
    module are never one module, whatever their components spell."""
    return (module[:1] == ("<std>",), components(module))


def main():
    failures = []

    for module, want in PINNED:
        got = module_tag(module)
        if got != want:
            failures.append("module_tag(%r) is %r, not the pinned %r"
                            % (module, got, want))

    paths = [()]
    for n in (1, 2, 3):
        paths.extend(itertools.product(ATOMS, repeat=n))
    paths.extend(("<std>", leaf) for leaf in STD_LEAVES)
    paths.extend(("<std>", a, b) for a in STD_LEAVES for b in STD_LEAVES)

    seen = {}
    for path in paths:
        tag = module_tag(path)
        if any(not (c.isascii() and (c.isalnum() or c == "_")) for c in tag):
            failures.append("module_tag(%r) is %r, which leaves [A-Za-z0-9_]"
                            % (path, tag))
        who = identity(path)
        if tag in seen and seen[tag] != who:
            failures.append("module_tag collides: %r and %r both render %r"
                            % (seen[tag], who, tag))
        seen[tag] = who
        back = decode(tag)
        if back != components(path):
            failures.append("module_tag(%r) = %r decodes to %r, not %r"
                            % (path, tag, back, components(path)))

    if failures:
        for f in failures:
            print("FAIL: " + f, file=sys.stderr)
        return 1
    print("module tag: %d paths, %d modules, %d tags, injective and decodable "
          "— ok" % (len(paths), len({identity(p) for p in paths}), len(seen)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
