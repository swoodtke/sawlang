#!/usr/bin/env python3
"""Conformance row B10 — two std FILES may each own one private type name.

DF-153a, closed by design 204. Design 82 makes each std file its own module and
design 144 makes type identity `(defining module, name)`, but the std sources
type-check as ONE `builtins` unit, so a second declaration of a name used to
collide:

    sawc/std/once.saw:64   enum State: Int { case Unset = 0, ... }
    <another std file>     enum State: Int { ... }
    -> error: enum `State` is defined multiple times  --> builtins:...

A user program with two modules like that compiles (design 144 landed it), so
this was the rule not holding where it is written to hold. It is
std-authoring-internal — no `.saw` test can express "a second std file" — so the
vehicle is this compiler-level test: it drops a second private `State` (and a
second private `MapSlot`) into the std tree, rebuilds the builtins over it, and
asserts both declarations survive with distinct identities and distinct layouts.

Run standalone or through `tools/battery.sh` (the `stdtypes` stage).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sawc"))

# A file INSIDE sawc/std/ is what makes it a std module: the defining-module id
# is keyed on the source path (`TypeChecker._vis_module_for_source`), so the
# probe file has to live where std lives. Unique per process, and removed in a
# `finally` whatever happens.
STD_DIR = os.path.join(ROOT, "sawc", "std")
LEAF = "df153a_probe_%d" % os.getpid()
PROBE_PATH = os.path.join(STD_DIR, LEAF + ".saw")

PROBE_SOURCE = """\
// Design 204 test fixture (tools/test_std_private_type_names.py). Written and
// removed by that test; it is never part of a real build.

// The same two private type names `std/once.saw` and `std/map.saw` own. Each
// file owns its own, so all four declarations coexist.
enum State: Int {
    case Cold = 7,
    case Warm = 8
}

struct MapSlot {
    weight: Int
}

func __df153a_probe_reading() -> Int {
    let slot = MapSlot(weight: 4)
    (State.Warm as Int) + slot.weight
}
"""

FAILURES = []


def check(condition, message):
    if not condition:
        FAILURES.append(message)


def main():
    with open(PROBE_PATH, "w") as f:
        f.write(PROBE_SOURCE)
    try:
        import sawc

        try:
            _ast, ns = sawc.build_builtin_namespace()
        except SystemExit:
            print("FAIL: the builtins did not type-check with a second private "
                  "`State`/`MapSlot` in the std tree (DF-153a has regressed)",
                  file=sys.stderr)
            return 1

        once = ns.module_type_names.get(("<std>", "once"), {})
        probe = ns.module_type_names.get(("<std>", LEAF), {})
        mapmod = ns.module_type_names.get(("<std>", "map"), {})

        check(once.get("State") == "State$m$std_once",
              "std/once.saw's `State` is not bound in its own module view: %r"
              % (once.get("State"),))
        check(probe.get("State") == "State$m$std_%s" % LEAF,
              "the probe file's `State` is not bound in its own module view: %r"
              % (probe.get("State"),))
        check(mapmod.get("MapSlot") == "MapSlot$m$std_map",
              "std/map.saw's `MapSlot` is not bound in its own module view: %r"
              % (mapmod.get("MapSlot"),))
        check(probe.get("MapSlot") == "MapSlot$m$std_%s" % LEAF,
              "the probe file's `MapSlot` is not bound in its own module view: "
              "%r" % (probe.get("MapSlot"),))

        # Two declarations, two symbols, two layouts — not one entry that the
        # second declaration overwrote.
        check("State$m$std_once" in ns.enums and
              "State$m$std_%s" % LEAF in ns.enums,
              "the two `State` enums are not both registered")
        left = ns.enums.get("State$m$std_once")
        right = ns.enums.get("State$m$std_%s" % LEAF)
        if left is not None and right is not None:
            check(left is not right, "the two `State` enums are one symbol")
            check(sorted(left.variant_order) == ["Ready", "Setting", "Unset"],
                  "std/once.saw's `State` lost its own variants: %r"
                  % (left.variant_order,))
            check(sorted(right.variant_order) == ["Cold", "Warm"],
                  "the probe file's `State` lost its own variants: %r"
                  % (right.variant_order,))
        # `std/map.saw`'s `MapSlot` is an ENUM and the probe's is a STRUCT, so
        # this pair also pins that the two never meet in the struct-vs-enum
        # conflict check either.
        lslot = ns.enums.get("MapSlot$m$std_map")
        rslot = ns.structs.get("MapSlot$m$std_%s" % LEAF)
        check(lslot is not None and rslot is not None,
              "the two `MapSlot` declarations are not both registered")
        if rslot is not None:
            check(list(rslot.field_order) == ["weight"],
                  "the probe file's `MapSlot` has the wrong layout: %r"
                  % (rslot.field_order,))

        # And NEITHER name leaks into the shared view a user program resolves
        # through — that is the DF-153b half of the same rule.
        check("State" not in ns.type_names,
              "`State` leaked into the shared name view")
        check("MapSlot" not in ns.type_names,
              "`MapSlot` leaked into the shared name view")
    finally:
        if os.path.exists(PROBE_PATH):
            os.remove(PROBE_PATH)

    if FAILURES:
        for f in FAILURES:
            print("FAIL: " + f, file=sys.stderr)
        return 1
    print("std private type names: two std files may each own one (DF-153a) — ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
