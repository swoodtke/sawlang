#!/usr/bin/env bash
#
# The full gate battery — what a design brief runs before it is called landed.
#
# Until design 192 this lived as an untracked scratch script that each session
# rewrote from the CLAUDE.md prose, which is the reason it is here: a gate list
# nobody can diff is a gate list that quietly loses an entry. This one is
# tracked, and adding a lane means editing it.
#
# Every stage is INDEPENDENT and every stage runs: the script does not stop at
# the first failure, because "the compiler tests are red" and "they are red AND
# so is the fixpoint" are different situations and you want to know which one
# you are in. The exit code is the number of failing stages.
#
# No stage runs the frozen Python compiler (sawc/): the lanes that tested it
# left the battery with the per-patch gate's move to sawc (SL-666), but for
# docverify, which stays until sawc has its equivalent.
#
#   tools/battery.sh                    # everything but the manual lanes
#   tools/battery.sh --quick            # skip the slow lanes (gmgate, linux)
#   tools/battery.sh compiler fixpoint  # named stages only
#   tools/battery.sh --list             # what the stages are
#
# The interpreter comes from $SAW_PYTHON, else ./.venv/bin/python under the
# repo root, else python3 — so this runs from a worktree with no venv of its
# own by pointing SAW_PYTHON at the main checkout's:
#
#   SAW_PYTHON=/path/to/main/.venv/bin/python tools/battery.sh
#
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 2

if [ -n "${SAW_PYTHON:-}" ]; then
    PY="$SAW_PYTHON"
elif [ -x "$REPO/.venv/bin/python" ]; then
    PY="$REPO/.venv/bin/python"
else
    PY="$(command -v python3)"
fi

if [ ! -x "$PY" ]; then
    echo "battery: no usable Python (set SAW_PYTHON)" >&2
    exit 2
fi

# stage name | slow? | description | command
#
# `slow` stages are the ones --quick drops: minutes each. A `manual` stage runs
# only when it is named: it is long and gates nothing, so a full battery leaves
# it out.
STAGES=(
    "compiler|no|the self-hosted compiler: unit programs, golden fixtures, the subset checker, the grammar lint|$PY compiler/tests/run.py"
    "fixpoint|no|Stage 2 (sawc built by sawc) agrees with Stage 1 on every lane's invocations, and Stage 3 = Stage 2|env SAW_FIXPOINT_FULL=1 $PY compiler/tests/fixpoint/fixpoint_lane.py"
    "grammarcorpus|no|every tracked .saw against GRAMMAR.md: its recorded verdict, one tree when accepted|$PY compiler/tests/grammar/corpus.py"
    "corpusdiff|no|every tests/corpus program through sawc against Stage 0's snapshot: no verdict moved from the baseline|$PY compiler/tests/corpusdiff/corpusdiff.py gate"
    "citations|no|the files nothing compiles: stale DF/SL citations, committed conflict markers|$PY tools/check_citations.py"
    "docverify|no|every Saw example in README/CLAUDE/spec/skill compiles as its marker claims|$PY tools/docverify.py"
    "toolchain|no|the toolchain resolver: four steps, the version check, the refusal|$PY tools/test_toolchain.py"
    "suitelock|no|the suite lock names its holder, heartbeats, reports its wait; build.sh hands the wait to the gate and gives the lock back on a TERM|$PY tools/test_suite_lock.py"
    "patchgate|no|the per-patch gate's decision per changed path, and the corpusdiff baseline's regression rule|$PY tools/test_patch_gate.py"
    "childgroups|no|a TERM to a runner ends every child group it started in a session of its own|$PY tools/test_child_groups.py"
    "floatvectors|no|the Float<->text vectors against CPython's own conversions|$PY tools/sawfloat.py verify --rule"
    "abidoc|no|runtime/ABI.md describes exactly the frozen seam set|$PY tools/test_runtime_abi_doc.py"
    "gmgate|yes|ownership + concurrency oracles, built by sawc, under Guard Malloc (macOS)|$PY tools/gmgate.py"
    "linux|yes|the run lane on Linux aarch64 and x86_64 (Rosetta) in the sawlang-linux VM; skips when it is down|__LINUX__"
)

usage() {
    echo "usage: tools/battery.sh [--quick] [--list] [stage ...]"
    echo
    echo "stages (a * marks one --quick skips, a + one that runs only when named):"
    for entry in "${STAGES[@]}"; do
        IFS='|' read -r name slow desc _cmd <<< "$entry"
        mark=" "
        [ "$slow" = "yes" ] && mark="*"
        [ "$slow" = "manual" ] && mark="+"
        printf "  %s %-15s %s\n" "$mark" "$name" "$desc"
    done
}

QUICK=0
WANTED=()
for arg in "$@"; do
    case "$arg" in
        --quick) QUICK=1 ;;
        --list|-l|-h|--help) usage; exit 0 ;;
        -*) echo "battery: unknown option $arg" >&2; usage >&2; exit 2 ;;
        *) WANTED+=("$arg") ;;
    esac
done

wanted() {
    [ ${#WANTED[@]} -eq 0 ] && return 0
    for w in "${WANTED[@]}"; do
        [ "$w" = "$1" ] && return 0
    done
    return 1
}

# The Linux lanes run in the sawlang-linux Lima VM through tools/linux.py, which
# never starts it (only the user can, from outside a sandboxed session). So the
# lane is opt-in by the VM's state: down (or no Lima installed), it SKIPS with
# linux.py's reason and passes; up, both arches must pass against the macOS run
# lane's expectations. A limactl that cannot report the state FAILS the lane:
# the skip stands for a VM known not to run, never for one nobody could see.
# That decision is `tools/linux.py lane`'s, pinned first by tools/test_linux.py
# against stub limactls, which needs no VM.
run_linux() {
    "$PY" tools/test_linux.py || return 1
    "$PY" tools/linux.py lane
}

echo "battery: $REPO"
echo "battery: python $PY"
started=$(date +%s)
FAILED=()
RAN=0
SKIPPED=()

for entry in "${STAGES[@]}"; do
    IFS='|' read -r name slow desc cmd <<< "$entry"
    wanted "$name" || continue
    if [ "$slow" = "manual" ] && [ ${#WANTED[@]} -eq 0 ]; then
        SKIPPED+=("$name")
        continue
    fi
    if [ "$QUICK" = "1" ] && [ "$slow" = "yes" ] && [ ${#WANTED[@]} -eq 0 ]; then
        SKIPPED+=("$name")
        continue
    fi
    echo
    echo "=============================================================="
    echo "  $name — $desc"
    echo "=============================================================="
    stage_start=$(date +%s)
    if [ "$cmd" = "__LINUX__" ]; then
        run_linux
    else
        $cmd
    fi
    rc=$?
    stage_elapsed=$(( $(date +%s) - stage_start ))
    RAN=$((RAN + 1))
    if [ $rc -ne 0 ]; then
        FAILED+=("$name")
        echo "  ---> $name FAILED (rc=$rc, ${stage_elapsed}s)"
    else
        echo "  ---> $name ok (${stage_elapsed}s)"
    fi
done

elapsed=$(( $(date +%s) - started ))
echo
echo "=============================================================="
if [ ${#SKIPPED[@]} -gt 0 ]; then
    echo "battery: skipped, by --quick or as run only when named: ${SKIPPED[*]}"
fi
if [ ${#FAILED[@]} -eq 0 ]; then
    echo "battery: $RAN stage(s) GREEN in ${elapsed}s"
    exit 0
fi
echo "battery: ${#FAILED[@]} of $RAN stage(s) FAILED in ${elapsed}s: ${FAILED[*]}"
echo
echo "Re-run one with its name: tools/battery.sh ${FAILED[0]}"
exit ${#FAILED[@]}
