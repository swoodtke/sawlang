#!/usr/bin/env python3
"""Ownership gate under Guard Malloc (design 159 unit 4).

A missing retain is INVISIBLE to an ordinary run. The surplus release lands in
a block libmalloc has already freed but not unmapped, so the program reads
correct values and exits 0 — until some later, unrelated allocation trips over
the damage. That is why DF-151b sat in the tree from design 73 (a by-value
argument) and design 147 (a local copy) with a green suite the whole time: at a
~15-35% per-run crash rate a single suite pass clears easily, and the two tests
that should have caught it were passing for the wrong reason.

Guard Malloc (`/usr/lib/libgmalloc.dylib`) puts each allocation on its own page
and UNMAPS it on free, so a release of a freed block faults AT the offending
instruction instead of corrupting a neighbour. Every program below went from
100% crash to 100% clean across the design 159 fix.

This lane is deliberately SMALL. Guard Malloc costs a page per allocation and
runs the whole suite far too slowly to gate on; what it needs to cover is the
ownership oracles, where a latent over-release is the failure mode that no
other check can see. Add a program here when it exists to prove something about
copies, retains, drops or refcounts.

TWO LANES (design 192 unit 4). The original `ownership` lane is about VALUES —
copies, retains, drops, refcounts, containers. The `concurrency` lane added
beside it is about the same failures where the value lives in a HEAP-RESIDENT
COROUTINE FRAME or crosses a task boundary: a frame handoff, a capture a task
holds while its spawner runs on, a group teardown, a channel send. Design 190's
audit found two CONFIRMED silent use-after-frees in that surface — both probes
exited 0 with plausible output — and the ordinary suite could not see either.
Under Guard Malloc they are instruction-level crashes. Measured on a probe that
returns a pointer into heap storage a suspending frame released (the shape
design 189 now refuses at compile time): NATIVE it prints a plausible byte and
exits 0; under this harness it takes SIGSEGV at the load, rc=139.

The concurrency lane runs FEWER repeats (5 vs 10) because it has a scheduler
under it: its programs interleave, so repeats buy variety rather than the
same trace again, and each one is slower.

Usage:
    python tools/gmgate.py [-n RUNS] [--lane ownership|concurrency|all] [-v]

`make gmgate` wires this up. macOS only — Guard Malloc is a macOS facility, so
elsewhere this reports SKIPPED rather than failing (see TESTING.md).
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO, "sawc", "sawc.py")
GMALLOC = "/usr/lib/libgmalloc.dylib"
OUT_DIR = os.path.join(REPO, ".build", "gmgate")

# The ownership lane. Each entry is an example that asserts something about
# ownership; the comment says which shape it pins.
OWNERSHIP_GATE = [
    # The undeclared `Copy` tier across every transfer class (design 159).
    "examples/df151b_implicit_tier_transfers.saw",
    # A closure env retained through struct copies (design 73). This one is the
    # reason the lane exists: its own `strong_count` assertions read correct
    # while the env was released three times, so Guard Malloc is the ONLY thing
    # that can police it.
    "examples/closure_copyable_struct_copied.saw",
    # A `Copy`-tier value copied out of a place, then the place overwritten
    # (design 147 unit B / DF-139a).
    "examples/df139a_copy_then_overwrite.saw",
    # A closure env's retains and releases counted against an Arc (design 73).
    "examples/closure_deinit_arc_balance.saw",
    "examples/closure_borrow_lend_balance.saw",
    # Container-slot read-out: an owning value copied OUT of a container the
    # container still owns — the `v[i]` / `m[k]` duplication rule.
    "examples/closure_vector_copy_get.saw",
    "examples/map_string_owning_value_balance.saw",
    "examples/set_algebra_owning_balance.saw",
    "examples/generic_for_loop_owning_balance.saw",
    # Implicit copies at a call argument, nested in a struct, and splatted into
    # a repeat literal.
    "examples/implicit_copy_call_arg.saw",
    "examples/implicit_copy_nested.saw",
    "examples/repeat_literal_implicit_copy.saw",
    # A refcounted value copied into an OPT-ENCODED destination, at all six
    # transfer sites (DF-151c). Its Arc counts prove the retains happen; only
    # Guard Malloc proves no surplus release does, since an over-release reads
    # correct until the freed block is reused.
    "examples/df151c_optional_dest_copy.saw",
    # A match scrutinee that no binding holds (DF-151d). A leak here inverts to
    # an over-release under a fix that drops one time too many — an escaping arm
    # binding is an alias into the very value being released — so the counts and
    # this lane police opposite failures of the same change.
    "examples/df151d_match_temporary_scrutinee.saw",
    # Optional ELEMENTS of a fixed array (DF-151e): the retain is driven by the
    # payload's type and the wrap follows it, at construction and at a write.
    "examples/df151e_optional_element_array.saw",
    # TUPLE drop glue (DF-151f). The leak and the over-release are one change:
    # elements now drop at scope exit AND a whole-tuple copy now retains them,
    # so getting either half wrong inverts this program's failure. The counts
    # catch a missing retain; only Guard Malloc catches a surplus release.
    "examples/df151f_tuple_drop_glue.saw",
    # TUPLE `.copy()` (DF-151i), the operation DF-151f's glue exists to balance.
    # An element-wise deep copy is exactly the shape this lane polices: a tuple
    # copy that ALIASED a refcounted element instead of retaining it reads
    # correct values and exits 0, and the surplus release lands at the second
    # tuple's scope exit where nothing else can see it.
    "examples/df151i_tuple_copy.saw",
    # The WHOLE-ELEMENT tuple write `t.0 = fresh` (DF-151j). Replacing an owning
    # element has to drop the old one exactly once, and this is the third way to
    # get that wrong: the write had no place at all before, so the drop is new
    # code on a slot that always holds a live value. Skipping it leaks (the live
    # count sees that); running it twice reads correct and faults only when the
    # freed block is reused, which is this lane's job.
    "examples/df151j_tuple_element_write.saw",
    # An assignment RHS reading out of storage the source keeps (DF-151h). The
    # exact DF-151b shape one statement kind over: `a = h.r` read correct and
    # freed twice, so the surplus release is invisible without Guard Malloc.
    "examples/df151h_assign_rhs_retain.saw",
    # A move-only param and a refcounted result crossing the DF-138a spawn-root
    # trampoline: the trampoline frame holds the value only long enough to hand
    # it down to the sub-frame, and takes the result back up. Both halves are a
    # move BETWEEN two frames the same task owns, so a drop on the wrong side of
    # the hand-off is exactly the over-release this lane exists to see. Its live
    # count proves nothing leaks; only Guard Malloc proves nothing is freed twice.
    "examples/coro_spawn_and_embed_owning.saw",
    # A frame local handed out through a TAIL `move` rather than a `return`
    # (DF-182d). The drop-flag clear that keeps the frame from dropping it again
    # now rides the done sequence; put it in the wrong place and the value is
    # freed twice while still reading correctly, which is this lane's whole brief.
    "examples/coro_tail_move_local.saw",
    # A `move` SCRUTINEE handed into a frame field by the optional-binding
    # dispatch (DF-182c). The store became a move and the drop-flag clear went
    # into both branches, which is two chances to release the same value twice —
    # a copying store that still cleared the flag, or a clear on a branch that
    # never took the payload. Its deinit count catches a leak; only Guard Malloc
    # catches the surplus release, which reads correct until the block is reused.
    "examples/coro_move_scrutinee_span.saw",
    # Data's copy-on-write separation plus the offset-aware eager fill. Since
    # design 165 the count is Arc's rather than hand-rolled, which is exactly
    # why these stay: the release now runs through Arc's two-phase drop into
    # DataBuf's deinit, so a miscount frees a buffer a live Data or slice still
    # points at — correct-reading natively, visible only here.
    "examples/data_cow_slice.saw",
    # Every Data mutation taking the uniqueness gate (design 165). Each
    # separation allocates a buffer, copies into it, and RELEASES the old
    # storage; getting that release wrong in either direction is invisible
    # natively — a leak reads correct, and a double release reads correct until
    # the block is reused. The program holds a sibling live across every one of
    # them precisely so a premature free has a live reader.
    "examples/data_cow_value_semantics.saw",
    # DATA-1: an iterator that OUTLIVES its Data — the use-after-free design 165
    # closes. Reverting `iter()` to its pre-165 shape (a raw pointer and no
    # retain) makes this program read `7 0 48` for `7 8 9`, so the suite catches
    # that regression on its own. It is in this lane for the read that does NOT
    # corrupt visibly: the iterator holds a retain now, so the source Data stays
    # alive with a count this lane can see miscounted in either direction.
    "examples/data_iter_outlives_source.saw",
    # Appending a Data to itself (design 165). The argument is a retain, so the
    # separation and the read race each other by construction: separate too
    # late and the memcpy source is a buffer `grow` has freed, separate without
    # re-reading and it is the destination being filled. Both read plausible
    # bytes natively.
    "examples/data_cow_self_append.saw",
]

# The CONCURRENCY lane (design 192 unit 4). Same failure mode, different
# storage: a suspending function's locals live in a heap-allocated frame, a
# spawned task's values live in a frame the spawner's stack does not own, and a
# group's teardown drops both. Every drop in here happens somewhere no stack
# discipline polices, which is why design 190's audit found two silent
# use-after-frees in this surface and the suite saw neither.
#
# Curated, not swept: a corpus sweep of every concurrency example takes 30-60
# minutes under Guard Malloc and would be flaky-adjacent (real threads, real
# timers). These are the OWNERSHIP oracles among them.
CONCURRENCY_GATE = [
    # --- Frame handoff: an owning value that lives across a suspension -------
    # A Deinit local held across a suspend. The frame is heap-resident, so the
    # local's storage outlives no stack frame and the drop happens at frame
    # death — the plainest version of everything below it.
    "examples/coro_deinit_across_suspend.saw",
    # A moved Arc PARAMETER: the caller hands ownership into the frame, so the
    # release belongs to the frame and the caller must not also make it. The
    # refcount reads correct either way; only Guard Malloc sees the second one.
    "examples/coro_moved_arc_param_deinit_once.saw",
    # A CONDITIONAL move of a cleanup-needing frame local — the drop-flag
    # shape. Two paths, one of which handed the value away, and a flag in the
    # frame deciding whether the frame still owns it. Getting the flag wrong in
    # either direction leaks or double-frees, and DF-182c/DF-182d were both
    # exactly this in another spelling.
    "examples/coro_conditional_move_across_suspend.saw",
    # Tuple DESTRUCTURING across a suspension: two bindings out of one value,
    # each its own frame field, each owning its element. A drop of the whole
    # tuple beside the elements' drops is the failure.
    "examples/coro_destructure_across_suspend.saw",
    # The NEGATIVE of the rule: a reference frame field is non-owning and must
    # never be dropped. A frame that drops one frees a value its CALLER still
    # owns, and the caller's own drop then lands in freed storage.
    "examples/coro_ref_param_deinit_once.saw",
    # The same negative in SPAWN position (design 201), which is where it is
    # load-bearing rather than merely true: the frame is boxed on the run queue,
    # its referent is the spawner's storage, and design 124 tears a task's own
    # values down eagerly at completion. A borrowed referent must be exempt from
    # that teardown, and the elements the task pushed must die once, with the
    # caller. Three Deinit-bearing elements, so a second drop lands on a page
    # Guard Malloc has already unmapped.
    "examples/spawn_ref_param_referent_deinit_once.saw",

    # --- Captures: an env the frame owns, and a root a task borrows ----------
    # A closure capturing a frame-resident Arc, held across a suspension. The
    # env is refcounted heap storage owned by the frame; DF-C1 was it being
    # released twice.
    "examples/coro_closure_deinit_once.saw",
    # A spawned TaskGroup child frame that OWNS closures — the env crosses into
    # a task's frame and dies with it.
    "examples/coro_closure_taskgroup.saw",
    # The nearest STILL-LEGAL cousin of design 188's ex-UAF probe (a capture
    # declared AFTER its group, now a compile error): declared BEFORE it, which
    # is the accepted order and the one whose soundness rests on LIFO
    # destruction actually holding at run time. If the group's Deinit ever
    # stopped joining before the captured roots die, this is the program that
    # crashes.
    "examples/spawn_capture_declared_before.saw",
    # The nearest still-legal cousin of design 189's ex-UAF probe (a `move` of
    # a borrowed root between spawn and join, now a compile error): the same
    # shapes with the borrow released where it should be. DF-189c handed a task
    # a freed `Vector` buffer, and `log` here is that same Vector.
    "examples/spawn_capture_join_releases.saw",
    # The join-release shape through a reference ARGUMENT (design 201): the
    # `Vector` is filled by one task, read by a second that borrows it SHARED
    # after the first join, and appended to by a third. Three tasks reach one
    # buffer across two releases, and every reallocating push happens while a
    # frame elsewhere holds a pointer to the root — which is the arrangement
    # that turns a release point off by one task into a fault here.
    "examples/conformance/K14_spawn_ref_param_join_releases.saw",

    # --- Join and teardown: who drops what, and when -------------------------
    # Design 124's eager teardown: a task's owned values deinit AT TASK
    # COMPLETION, not at group death. The drop moved; anything that kept the
    # old one too frees twice.
    "examples/taskgroup_eager_teardown.saw",
    # A result NOBODY joins. It outlives its frame in a group-owned cell and is
    # dropped exactly once at group teardown — the path with no `join` to make
    # the ownership transfer explicit.
    "examples/taskgroup_result_unjoined_once.saw",
    # The same question with real worker threads stealing: a frame result
    # dropped exactly once when the completing thread and the joining thread
    # are different.
    "examples/taskgroup_threads_deinit_once.saw",
    # Design 134's slot reuse: the frame ALLOCATION is released at completion
    # and its run-queue slot returns to a free list, so a later task's frame
    # lands where a finished one was. Guard Malloc unmaps the old page, which
    # is what turns "a stale handle reads the new occupant" into a fault.
    "examples/taskgroup_slot_reuse_o_live.saw",

    # --- The executor's own drive paths (design 206) --------------------------
    # A task spawned BEFORE main's first suspension, where that suspension is a
    # reactor park. `main` is a coroutine frame here — it was a plain C function
    # until design 206 — so main's `TcpListener`, its accepted `TcpStream` and
    # the worker's own stream all live in heap frames the executor drops, and
    # the worker's frame dies at completion while main is still parked. Guard
    # Malloc is what turns "main's frame was released a beat early" into a
    # fault rather than a passing test.
    "examples/spawned_task_runs_before_reactor_park.saw",
    # The semaphore-wrapper shape: a helper frame between a task and a channel
    # `receive()`. Two tasks pass one token through a channel, so the value
    # crosses task boundaries while `acquire`'s frame is EMBEDDED BY VALUE in
    # each worker's frame — a sub-frame whose storage is interior to another
    # allocation, which is exactly the arrangement a stale interior pointer
    # survives unnoticed under the ordinary allocator.
    "examples/channel_receive_through_helper.saw",

    # --- Values crossing a task boundary -------------------------------------
    # Owning values moved through a cooperative channel: the sender gives up
    # ownership, the receiver takes it, and exactly one of them drops.
    "examples/channel_recv_producer_consumer.saw",
    # An owning CONTAINER moved into a task — a Vector, a Map, a Data. `Data`
    # is copy-on-write over Arc-owned storage since design 165, so a container
    # crossing into a frame is the COW question and the Send question at once.
    "examples/taskgroup_send_containers.saw",

    # --- Errors and captures inside a frame (design 196) ---------------------
    # Each of these was a compiler refusal or an ICE until design 196, so none
    # of them had ever RUN — and every one puts an owning value somewhere the
    # frame owns it: exactly the storage this lane exists to police.
    #
    # A BOXED error built into the frame's own result slot across a suspension.
    # The box is heap storage the frame owns until `join` (or teardown) takes
    # it, and its payload is destroyed through the vtable's destructor slot,
    # not through a static type — so a drop counted twice never shows in a
    # refcount, only here.
    "examples/erased_error_across_suspension.saw",
    # The same box travelling through a SPAWNED task's result cell, one nesting
    # level deeper (a `Vector` Ok payload), with a downcast beside it —
    # `take<T>()` CONSUMES the box and moves the payload out on a hit, drops it
    # on a miss, and both paths run here.
    "examples/erased_error_spawned_container_result.saw",
    # A split `try { } catch { }`: the caught error lands in a FRAME FIELD in
    # one state and is read in another, and the error owns a String. Beside it,
    # an owning `Vector` Ok payload moved out of a `try` in the try arm, the
    # whole shape inside a spawned task, and thirteen positions' worth of
    # states to drop it in exactly once.
    "examples/coro_try_block_positions.saw",
    # `try` PROPAGATION out of a frame: the error is wrapped into the result
    # slot and the frame finishes, including the design-56 RE-BOX of a concrete
    # error into an erased return — a fresh allocation on the failing path of a
    # function that is also handing back an owning Ok payload on the other.
    "examples/coro_try_propagate_suspending.saw",
    # Reassigning an owning frame local: the field's OLD payload has to be
    # dropped exactly once by the store that replaces it. A String, a String
    # derived from the old one, and a `Vector` moved in from a sibling local.
    "examples/coro_reassign_owning_local.saw",
    # The canonical shared-counter idiom, which had no legal spelling at all
    # until design 196 unit 4: four MT tasks each carrying their own `Arc`
    # copy into a frame, mutating the shared payload under the lock, and
    # releasing on whichever worker thread finishes them.
    "examples/conformance/K13_mt_sum_under_mutex.saw",
]

LANES = {
    "ownership": (OWNERSHIP_GATE, 10),
    "concurrency": (CONCURRENCY_GATE, 5),
}


def build(rel: str, verbose: bool):
    """Compile one gate program. Returns its binary path, or None if absent."""
    src = os.path.join(REPO, rel)
    if not os.path.exists(src):
        return None
    stem = os.path.splitext(os.path.basename(rel))[0]
    out = os.path.join(OUT_DIR, stem)
    os.makedirs(OUT_DIR, exist_ok=True)
    r = subprocess.run([sys.executable, SAWC, src, "-o", out],
                       capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0:
        if verbose:
            sys.stderr.write(r.stdout + r.stderr)
        return False
    return out


def run_under_gmalloc(binary: str, runs: int):
    """Run `binary` `runs` times under Guard Malloc; return the failure list."""
    env = dict(os.environ)
    env["DYLD_INSERT_LIBRARIES"] = GMALLOC
    # Guard the page BEFORE the allocation too, so an underflowing write faults
    # as readily as an overflowing one.
    env["MALLOC_PROTECT_BEFORE"] = "1"
    failures = []
    for i in range(runs):
        r = subprocess.run([binary], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            failures.append((i, r.returncode))
    return failures


def run_lane(name, programs, runs, verbose):
    """Build and run one lane. Returns `(checked, failed, missing)`."""
    failed, checked, missing = [], 0, []
    print(f"gmgate [{name}]: {len(programs)} program(s) x {runs} runs")
    for rel in programs:
        binary = build(rel, verbose)
        if binary is None:
            missing.append(rel)
            continue
        if binary is False:
            print(f"  \033[1;31mBUILD FAIL\033[0m {rel}")
            failed.append(rel)
            continue
        failures = run_under_gmalloc(binary, runs)
        checked += 1
        if failures:
            codes = ", ".join(f"run {i} rc={rc}" for i, rc in failures[:5])
            print(f"  FAIL {rel}: {len(failures)}/{runs} crashed ({codes})")
            failed.append(rel)
        elif verbose:
            print(f"  ok   {rel}: {runs}/{runs} clean")
    return checked, failed, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--runs", type=int, default=None,
                    help="runs per program, OVERRIDING each lane's own default "
                         "(ownership 10, concurrency 5)")
    ap.add_argument("--lane", choices=sorted(LANES) + ["all"], default="all",
                    help="which lane to run (default all)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if sys.platform != "darwin" or not os.path.exists(GMALLOC):
        print("gmgate: SKIPPED — Guard Malloc is a macOS facility "
              f"({GMALLOC} not present)")
        return 0

    lanes = sorted(LANES) if args.lane == "all" else [args.lane]
    failed, checked, missing = [], 0, []
    for lane in lanes:
        programs, default_runs = LANES[lane]
        runs = args.runs if args.runs is not None else default_runs
        c, f, m = run_lane(lane, programs, runs, args.verbose)
        checked += c
        failed.extend(f)
        missing.extend(m)

    for rel in missing:
        print(f"  note: {rel} is not in the tree — gate entry skipped")

    print(f"gmgate: {checked} program(s) under Guard Malloc across "
          f"{len(lanes)} lane(s), {len(failed)} failing")
    if failed:
        print("\nA failure here is an OVER-RELEASE or a use-after-free, not a "
              "flake:\nGuard Malloc unmaps freed blocks, so the fault lands at "
              "the instruction\nthat touched one. Re-run the named program "
              "directly to see it:\n"
              f"  DYLD_INSERT_LIBRARIES={GMALLOC} .build/gmgate/<name>")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
