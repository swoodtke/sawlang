#!/usr/bin/env python3
"""Ownership and concurrency oracles, built by sawc2, run under Guard Malloc.

A surplus release is invisible to an ordinary run: it lands in a block
libmalloc has freed but not unmapped, so the program reads correct values and
exits 0 until some unrelated allocation trips over the damage. A deinit fires
on the 1 -> 0 edge and never again, so neither a refcount assertion nor a
deinit-print count sees a second release. Guard Malloc
(`/usr/lib/libgmalloc.dylib`) puts each allocation on its own page and unmaps
it on free, so the release faults at the instruction that makes it.

TWO LANES. `ownership` (10 runs a program) is about values: copies, retains,
drops, refcounts, containers. `concurrency` (5 runs) is the same failure where
the value lives in a heap-resident coroutine frame or crosses a task boundary;
its programs run under a scheduler, so a repeat buys interleaving variety
rather than the same trace, and each is slower.

THE LISTS. Each lane is a list of categories, each category the shape its
programs police. A category names three kinds of program:
  twins      tests/corpus twins of the programs the lane ran on Stage 0;
  stand-ins  other programs sawc2 builds that police the same shape, held
             until a blocked twin builds;
  blocked    twins sawc2 refuses today, each with the rule of its first
             refusal and the unit that clears it (or `unfiled`).
A tests/corpus program is judged by its own directives; a compiler/tests/run
program by Stage 0's recorded run of it, as the run lane judges it. Every
run of every program must meet its oracle: a fault, a signal or wrong output
fails. A blocked program is still built, and fails the lane once sawc2 builds
it or refuses it by another rule, so the list cannot go stale silently.

COVERAGE: ownership runs a program in 6 of its 6 categories, and 19 of its 26
Stage 0 programs build; concurrency runs a program in 6 of its 6 categories,
and 19 of its 25 Stage 0 programs build.

THE SELF-TEST. `gmgate_surplus_release.saw` releases one block twice. Before
the lanes count, it must pass natively and fault under Guard Malloc; a lane
that cannot make it fault sees nothing.

Usage:
    python tools/gmgate.py [-n RUNS] [--lane ownership|concurrency|all] [-v]
                           [--no-build] [--list]

macOS only: elsewhere it reports SKIPPED and exits 0.
"""
import argparse
import collections
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tests"))
sys.path.insert(0, os.path.join(REPO, "compiler", "tests", "run"))

import oracle  # noqa: E402  (puts coro/, compiler/tools and tools/ on the path)
import build  # noqa: E402
import child_groups  # noqa: E402
import expect  # noqa: E402
import gate_jobs  # noqa: E402
import run_lane  # noqa: E402

GMALLOC = "/usr/lib/libgmalloc.dylib"
OUT_DIR = os.path.join(REPO, ".build", "gmgate")
SELF_TEST = "tools/gmgate_surplus_release.saw"
CORPUS = "tests/corpus/"
RUN_LANE = "compiler/tests/run/"
# Guard Malloc makes every allocation a page, so a run takes far longer than
# the run lane allows one.
RUN_TIMEOUT = 300
# What Guard Malloc itself writes to standard error, which no program prints:
# its banner, and the refusal of the sysctl that turns off address reuse,
# which only root may set.
_BANNER = re.compile(r"^(?:GuardMalloc\[[^\]]*\]: |Sysctl \(debug\.toggle_address_reuse\) error: ).*\n?", re.M)
# The docstring's COVERAGE statement: a paragraph, compared as one line.
_COVERAGE = re.compile(r"^COVERAGE: (.*?)\n\n", re.M | re.S)
_UNIT = re.compile(r"^(SL-\d+|unfiled)$")

Category = collections.namedtuple("Category", "name shape twins stand_ins blocked")
# `why` is the gap in a few words; `rule` is the first refusal's rule.
Blocked = collections.namedtuple("Blocked", "path rule unit why")

CLOSURE_OWNING = "a closure capturing a value that owns something is not in the backend"

OWNERSHIP = (
    Category(
        "copy tier", "the undeclared Copy tier and implicit copies, at every transfer site",
        twins=(
            # A Copy argument and a Copy value nested in a struct run copy().
            CORPUS + "implicit_copy_call_arg.saw",
            CORPUS + "implicit_copy_nested.saw",
            # A copy read out of storage the source still owns, then the source
            # overwritten; a repeat literal retaining once per slot.
            CORPUS + "df139a_copy_then_overwrite.saw",
            CORPUS + "repeat_literal_implicit_copy.saw",
        ),
        stand_ins=(
            # Heap Strings copied through an enum payload and a struct field
            # projection, in a loop that turns an imbalance into heap damage.
            CORPUS + "owning_aggregate_copy.saw",
            # The copy hook at a binding, a tuple, an Optional, a generic
            # body, a field and a payload.
            RUN_LANE + "copy_hook_conformance.saw",
        ),
        blocked=(
            Blocked(CORPUS + "df151b_implicit_tier_transfers.saw", "mono.not-yet", "SL-525", CLOSURE_OWNING),
        )),
    Category(
        "closure environments", "a closure environment retained through copies and released once",
        twins=(),
        stand_ins=(
            # Non-escaping environments: explicit, implicit and `[copy p]`
            # captures, and a closure built inside another.
            RUN_LANE + "closure_captures.saw",
        ),
        blocked=(
            Blocked(CORPUS + "closure_copyable_struct_copied.saw", "mono.not-yet", "SL-525", CLOSURE_OWNING),
            Blocked(CORPUS + "closure_deinit_arc_balance.saw", "mono.not-yet", "SL-525", CLOSURE_OWNING),
            Blocked(CORPUS + "closure_borrow_lend_balance.saw", "mono.not-yet", "SL-525", CLOSURE_OWNING),
        )),
    Category(
        "container read-out", "an owning value copied out of a container that keeps its own",
        twins=(
            CORPUS + "map_string_owning_value_balance.saw",
            # Set algebra over Arc-holding elements keeps the counts balanced.
            CORPUS + "set_algebra_owning_balance.saw",
            # A generic body's `for` over Arc-holding elements releases each
            # iteration's copy.
            CORPUS + "generic_for_loop_owning_balance.saw",
        ),
        stand_ins=(
            # A String-holding element read out of a Vector, and the copy and
            # deinit counts of each tier's read.
            CORPUS + "place_read_retains_owning.saw",
            CORPUS + "place_value_read_retain_oracle.saw",
            # Replaced, removed and rehashed Map entries, and a Vector slot
            # overwritten, each destroyed once.
            RUN_LANE + "map_drops.saw",
            RUN_LANE + "owning_vector.saw",
            # A NoCopy Map key and Set element, hashed and compared in place:
            # inserted, overwritten, borrowed, removed and torn down, each key
            # dropped once. Stage 0 refuses a NoCopy key, so none is a twin.
            CORPUS + "map_nocopy_key_error.saw",
            CORPUS + "map_nocopy_key_literal_error.saw",
            CORPUS + "set_nocopy_key_error.saw",
        ),
        blocked=(
            Blocked(CORPUS + "closure_vector_copy_get.saw", "mono.not-yet", "SL-525",
                    "an escaping closure's environment is not built"),
        )),
    Category(
        "optional, match and tuple transfers",
        "copies into optional destinations, match scrutinee temporaries, tuple glue, assignment sources",
        twins=(
            CORPUS + "df151c_optional_dest_copy.saw",
            # An array of optionals, a tuple's drop glue, a whole-element write
            # through a tuple index, and an assignment source read out of storage.
            CORPUS + "df151e_optional_element_array.saw",
            CORPUS + "df151f_tuple_drop_glue.saw",
            CORPUS + "df151j_tuple_element_write.saw",
            CORPUS + "df151h_assign_rhs_retain.saw",
            CORPUS + "df151i_tuple_copy.saw",
        ),
        stand_ins=(
            # Every face of the payload read retains once, and the payload
            # outlives the source it was read from.
            CORPUS + "optional_payload_read_retains.saw",
            CORPUS + "conformance/V99_every_payload_read_retains_once.saw",
            CORPUS + "optional_field_store_retain.saw",
            # A String scrutinee matched against literals, then used again.
            CORPUS + "match_string_scrutinee_refcount.saw",
            # Each owning element of a destructured tuple drops once.
            CORPUS + "let_tuple_destructure_owning_move.saw",
            # A heap String auto-wrapped into Ok from a tail expression.
            CORPUS + "autowrap_ok_no_premature_free.saw",
        ),
        blocked=(
            Blocked(CORPUS + "df151d_match_temporary_scrutinee.saw", "slice.not-yet", "SL-674",
                    "a value-producing `break` is not in the slice"),
        )),
    Category(
        "hand-off between one task's frames", "a value moved between frames one task owns, dropped on one side",
        twins=(
            CORPUS + "coro_spawn_and_embed_owning.saw",
            CORPUS + "coro_tail_move_local.saw",
            CORPUS + "coro_move_scrutinee_span.saw",
        ),
        stand_ins=(
            # A payload moved out of a driven match arm to each destination.
            CORPUS + "coro_driven_match_move_out_releases_once.saw",
            # A hoisted suspending call's result consumed by value.
            CORPUS + "coro_hoisted_call_arg_consumed_once.saw",
            # A root's owned arguments and its result through a drive site.
            RUN_LANE + "drive_ownership.saw",
        ),
        blocked=()),
    Category(
        "Data copy-on-write", "a separation that releases the old storage while a sibling still reads it",
        twins=(
            CORPUS + "data_cow_slice.saw",
            CORPUS + "data_cow_value_semantics.saw",
            CORPUS + "data_cow_self_append.saw",
        ),
        stand_ins=(),
        blocked=(
            Blocked(CORPUS + "data_iter_outlives_source.saw", "name.undefined", "SL-596",
                    "DataIterator is not in the new std"),
        )),
)

CONCURRENCY = (
    Category(
        "frame hand-off", "an owning value that lives in a heap frame across a suspension",
        twins=(
            # A Deinit local, a conditional move decided by a frame drop flag,
            # a destructured tuple, and a reference field that must never drop.
            CORPUS + "coro_deinit_across_suspend.saw",
            CORPUS + "coro_conditional_move_across_suspend.saw",
            CORPUS + "coro_destructure_across_suspend.saw",
            CORPUS + "coro_ref_param_deinit_once.saw",
            CORPUS + "coro_moved_arc_param_deinit_once.saw",
            CORPUS + "spawn_ref_param_referent_deinit_once.saw",
        ),
        stand_ins=(
            # A hoisted intermediate dies at its statement's end, once.
            CORPUS + "expr_suspend_deinit_once.saw",
            # An `if let` over a `move` scrutinee releases its payload once.
            CORPUS + "conformance/O12_iflet_move_binding_released_in_coroutine.saw",
            # A task cancelled during its offloaded call keeps its frame until
            # the call has written into it and the take has returned.
            RUN_LANE + "offload_cancel_waits_for_the_call.saw",
        ),
        blocked=()),
    Category(
        "captures", "an environment a frame owns, and a root a task borrows",
        twins=(
            CORPUS + "spawn_capture_declared_before.saw",
            CORPUS + "spawn_capture_join_releases.saw",
            CORPUS + "conformance/K14_spawn_ref_param_join_releases.saw",
        ),
        stand_ins=(
            # Closures in a suspending method, each holding its own handle to
            # the frame's receiver, one nested in another.
            CORPUS + "coro_closure_captures_self_nested.saw",
        ),
        blocked=(
            Blocked(CORPUS + "coro_closure_deinit_once.saw", "mono.not-yet", "SL-525", CLOSURE_OWNING),
            Blocked(CORPUS + "coro_closure_taskgroup.saw", "mono.not-yet", "SL-525",
                    "an escaping closure's environment is not built"),
        )),
    Category(
        "join and teardown", "who drops a task's values, and when",
        twins=(
            CORPUS + "taskgroup_eager_teardown.saw",
            CORPUS + "taskgroup_result_unjoined_once.saw",
            CORPUS + "taskgroup_slot_reuse_o_live.saw",
        ),
        stand_ins=(
            # At main's return the background group cancels and joins its
            # tasks, whose owned values deinit on the cancel path.
            CORPUS + "conformance/K87_background_group_cancels_then_joins_at_exit.saw",
            # A detached task's result drops when the task finishes.
            CORPUS + "conformance/K89_detach_gives_up_the_result.saw",
        ),
        blocked=(
            Blocked(CORPUS + "taskgroup_threads_deinit_once.saw", "call.label", "SL-578",
                    "`TaskGroup(threads:)` is not in the new std"),
        )),
    Category(
        "the executor's drive paths", "main as a frame the executor drives, beside the tasks it spawns",
        twins=(
            CORPUS + "channel_receive_through_helper.saw",
            CORPUS + "spawned_task_runs_before_reactor_park.saw",
        ),
        stand_ins=(
            # A function run as a task root, as an embedded child and directly
            # from main, which makes main a frame.
            RUN_LANE + "task_spawn_and_embed.saw",
            # Valued, Void and cancelled background tasks.
            CORPUS + "background_task_spawn.saw",
        ),
        blocked=()),
    Category(
        "values crossing a task boundary", "an owning value moved into a task, dropped by exactly one side",
        twins=(
            CORPUS + "channel_recv_producer_consumer.saw",
        ),
        stand_ins=(
            # Root arguments written into the task box's slots, a joined
            # result, a cancelled task joined, a detached one. Its String is a
            # literal, so the box, not a heap payload, is what it polices.
            RUN_LANE + "task_spawn.saw",
        ),
        blocked=(
            Blocked(CORPUS + "taskgroup_send_containers.saw", "call.label", "SL-578",
                    "`TaskGroup.init()` has no `threads:` label"),
        )),
    Category(
        "errors in a frame", "an error or Ok payload the frame owns across a suspension",
        twins=(
            CORPUS + "coro_try_block_positions.saw",
            CORPUS + "coro_reassign_owning_local.saw",
            # An erased error boxed in a frame, rendered through its vtable
            # after the suspension, and its box torn down once.
            CORPUS + "erased_error_across_suspension.saw",
            CORPUS + "coro_try_propagate_suspending.saw",
        ),
        stand_ins=(
            # An inline catch whose block suspends, over an error that owns a
            # String field.
            CORPUS + "coro_suspending_call_in_inline_catch.saw",
        ),
        blocked=(
            Blocked(CORPUS + "erased_error_spawned_container_result.saw", "slice.not-yet", "SL-745",
                    "downcasting an erased box with `is` or `take` is not in the slice"),
            Blocked(CORPUS + "conformance/K13_mt_sum_under_mutex.saw", "call.label", "SL-578",
                    "`TaskGroup.init()` has no `threads:` label"),
        )),
)

LANES = {
    "ownership": (OWNERSHIP, 10),
    "concurrency": (CONCURRENCY, 5),
}


def rel(path):
    return os.path.relpath(path, REPO)


def run_programs(categories):
    return [p for c in categories for p in c.twins + c.stand_ins]


def coverage_text():
    """The docstring's COVERAGE statement, as the lists determine it."""
    parts = []
    for name, (categories, _) in LANES.items():
        covered = sum(1 for c in categories if c.twins or c.stand_ins)
        twins = sum(len(c.twins) for c in categories)
        stage0 = twins + sum(len(c.blocked) for c in categories)
        parts.append("%s runs a program in %d of its %d categories, and %d of its %d Stage 0 programs build"
                     % (name, covered, len(categories), twins, stage0))
    return "; ".join(parts) + "."


def list_problems():
    """Every way the lists break this module's rules, without building."""
    problems = []
    seen = collections.Counter()
    for lane, (categories, _) in LANES.items():
        for c in categories:
            for path in run_programs([c]) + [b.path for b in c.blocked]:
                seen[path] += 1
                if not os.path.exists(os.path.join(REPO, path)):
                    problems.append("%s: %s is not in the tree" % (lane, path))
                elif not path.startswith((CORPUS, RUN_LANE)):
                    problems.append("%s: %s is neither a tests/corpus nor a compiler/tests/run program" % (lane, path))
            for path in run_programs([c]):
                full = os.path.join(REPO, path)
                if not os.path.exists(full):
                    continue
                if path.startswith(CORPUS) and expect.read(full).expect in ("error", "skip"):
                    problems.append("%s: %s states no run (EXPECT: %s)" % (lane, path, expect.read(full).expect))
                if path.startswith(RUN_LANE) and any(run_lane.headers(full)):
                    problems.append("%s: %s carries a due or differs header, so Stage 0's run is no oracle for it"
                                    % (lane, path))
            for b in c.blocked:
                if not b.path.startswith(CORPUS):
                    problems.append("%s: blocked %s is not a tests/corpus twin" % (lane, b.path))
                if not _UNIT.match(b.unit):
                    problems.append("%s: blocked %s names no unit (%r)" % (lane, b.path, b.unit))
    problems.extend("%s is listed %d times" % (path, n) for path, n in sorted(seen.items()) if n > 1)
    stated = _COVERAGE.search(__doc__)
    if stated is None or " ".join(stated.group(1).split()) != coverage_text():
        problems.append("the docstring's COVERAGE line is stale; it reads: COVERAGE: " + coverage_text())
    return problems


def binary_of(path):
    return os.path.join(OUT_DIR, os.path.splitext(path)[0].replace("/", "__"))


def sawc2_build(path):
    """sawc2's build of `path`: (binary or None, the first refusal (rule,
    position, message) or None, what it printed)."""
    src = os.path.join(REPO, path)
    out = binary_of(path)
    if os.path.exists(out):
        os.remove(out)
    code, found, log, _ = oracle.sawc2_build(src, out, expect.read(src).flags)
    return (out if code == 0 else None), (found[0] if found else None), log


def run(binary, guarded):
    """(exit status, or None on a timeout; stdout; stderr), from the
    repository root, under Guard Malloc when `guarded`."""
    env = dict(os.environ)
    if guarded:
        env["DYLD_INSERT_LIBRARIES"] = GMALLOC
        # Guard the page before each block too, so an underflowing access
        # faults as readily as an overflowing one.
        env["MALLOC_PROTECT_BEFORE"] = "1"
    try:
        r = subprocess.run([binary], cwd=REPO, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "", ""
    out = r.stdout.decode("utf-8", "replace")
    err = _BANNER.sub("", r.stderr.decode("utf-8", "replace"))
    return r.returncode, out, err


def judge(path, code, stdout, stderr):
    """None when a run meets `path`'s oracle, else the first way it does not."""
    if code is None:
        return "timed out after %ds" % RUN_TIMEOUT
    if path.startswith(RUN_LANE):
        rec, why = run_lane.stage0_run(os.path.join(REPO, path))
        if rec is None:
            return why
        diff = oracle.compare_run(rec, code, stdout, stderr)
        return None if diff is None else "%s: %s" % diff
    found = expect.judge(expect.read(os.path.join(REPO, path)), code, stdout, stderr)
    if found is not None and code < 0:
        return "%s (%s)" % (oracle.exit_text(code), found)
    return found


def check_run(item):
    """One listed program: (path, failures, how many runs were clean)."""
    path, runs = item
    binary, refusal, log = sawc2_build(path)
    if binary is None:
        first = "%s at %s: %s" % refusal if refusal else oracle.first_error(log)
        return path, ["sawc2 does not build it: %s" % first], 0
    failures = []
    for k in range(runs):
        why = judge(path, *run(binary, guarded=True))
        if why is not None:
            failures.append("run %d: %s" % (k + 1, why))
    return path, failures, runs - len(failures)


def check_blocked(b):
    """A blocked twin: (path, failures). It fails once sawc2 builds it or
    refuses it first by a rule other than the one listed."""
    binary, refusal, log = sawc2_build(b.path)
    if binary is not None:
        return b.path, ["sawc2 builds it now (listed as blocked on %s): move it to the category's twins" % b.unit]
    if refusal is None:
        return b.path, ["sawc2 refuses it with no ERROR line: %s" % oracle.first_error(log)]
    if refusal[0] != b.rule:
        return b.path, ["sawc2 refuses it first by %s at %s, not %s: update its reason and unit"
                        % (refusal[0], refusal[1], b.rule)]
    return b.path, []


def self_test():
    """The failures of the surplus-release probe: it must meet its
    directives natively and fault under Guard Malloc."""
    binary, refusal, log = sawc2_build(SELF_TEST)
    if binary is None:
        return ["sawc2 does not build it: %s" % ("%s at %s: %s" % refusal if refusal else oracle.first_error(log))]
    failures = []
    native = judge(SELF_TEST, *run(binary, guarded=False))
    if native is not None:
        failures.append("its native run fails (%s), so it no longer shows what only Guard Malloc sees" % native)
    code, _, _ = run(binary, guarded=True)
    if code is None or code >= 0:
        failures.append("under Guard Malloc it exits %s instead of faulting: the lane is blind"
                        % ("by timeout" if code is None else code))
    return failures


def print_lists():
    for lane, (categories, runs) in LANES.items():
        print("%s (%d runs a program)" % (lane, runs))
        for c in categories:
            print("  %s: %s" % (c.name, c.shape))
            for kind, paths in (("twin", c.twins), ("stand-in", c.stand_ins)):
                for p in paths:
                    print("    %-9s %s" % (kind, p))
            for b in c.blocked:
                print("    %-9s %s (%s, %s: %s)" % ("blocked", b.path, b.rule, b.unit, b.why))
    print("COVERAGE: " + coverage_text())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--runs", type=int, default=None,
                    help="runs per program, overriding each lane's own (ownership 10, concurrency 5)")
    ap.add_argument("--lane", choices=sorted(LANES) + ["all"], default="all", help="which lane to run (default all)")
    ap.add_argument("--no-build", action="store_true", help="use the sawc2 already built")
    ap.add_argument("--list", action="store_true", help="print the lists and check them, building nothing")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    child_groups.install()

    problems = list_problems()
    if args.list:
        print_lists()
    for p in problems:
        print("gmgate: " + p)
    if args.list or problems:
        return 1 if problems else 0

    if sys.platform != "darwin" or not os.path.exists(GMALLOC):
        print("gmgate: SKIPPED: Guard Malloc is a macOS facility (%s not present)" % GMALLOC)
        return 0
    if not args.no_build and not build.handed_down():
        ok, output = build.build_sawc2()
        if not ok:
            print(output)
            print("gmgate: sawc2 did not build")
            return 1

    start = time.monotonic()
    lanes = sorted(LANES) if args.lane == "all" else [args.lane]
    items, blocked = [], []
    for lane in lanes:
        categories, default_runs = LANES[lane]
        runs = args.runs if args.runs is not None else default_runs
        items.extend((p, runs) for p in run_programs(categories))
        blocked.extend(b for c in categories for b in c.blocked)
    os.makedirs(OUT_DIR, exist_ok=True)
    blind = self_test()
    ran = gate_jobs.map_ordered(check_run, items)
    still = gate_jobs.map_ordered(check_blocked, blocked)

    failed = 0
    if blind:
        failed += 1
        for f in blind:
            print("  FAIL %s: %s" % (SELF_TEST, f))
    elif args.verbose:
        print("  ok   %s: passes natively, faults under Guard Malloc" % SELF_TEST)
    for path, failures, clean in ran:
        if failures:
            failed += 1
            print("  FAIL %s: %s" % (path, "; ".join(failures[:3])))
        elif args.verbose:
            print("  ok   %s: %d/%d clean" % (path, clean, clean))
    for path, failures in still:
        if failures:
            failed += 1
            print("  FAIL %s: %s" % (path, failures[0]))
        elif args.verbose:
            print("  blocked %s" % path)
    print("gmgate: %d program(s) under Guard Malloc across %s, %d blocked twin(s) still refused; %d failing (%.0fs)"
          % (len(items), " and ".join(lanes), len(blocked), failed, time.monotonic() - start))
    if failed:
        print("A run that faults here is a surplus release or a use-after-free, not a flake: Guard Malloc\n"
              "unmaps freed blocks, so the fault lands at the instruction that touched one. Rerun it:\n"
              "  DYLD_INSERT_LIBRARIES=%s %s/<name>" % (GMALLOC, rel(OUT_DIR)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
