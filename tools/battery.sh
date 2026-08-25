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
# the first failure, because "the suite is red" and "the suite is red AND so is
# irdet" are different situations and you want to know which one you are in.
# The exit code is the number of failing stages.
#
#   tools/battery.sh                    # everything
#   tools/battery.sh --quick            # skip the slow lanes (sos, freestanding, bootstrap)
#   tools/battery.sh suite irdet        # named stages only
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
# `slow` stages are the ones --quick drops: minutes each, and each has its own
# make target for when you want it alone.
#
# ORDERING NOTE (design 220 D4): `suite` runs before `irdet` in this list —
# deliberately kept that way, not required. `suite` publishes
# `.build/test_runner_last` with a manifest of optimized-IR artifacts;
# `irdet --all` reuses one side of its byte-compare from that manifest when
# it is fresh, which is cheapest right after `suite` just built it. Running
# `irdet` alone (`tools/battery.sh irdet`), or any other stage ordering, is
# still fully correct — D4's byte-compare + three-way verify catches a stale
# or absent manifest as either "no reuse" (empty/missing manifest, today's
# compile-both path) or a self-reporting "violated invariant" (a stale one),
# never a false pass. Reordering these two stages trades reuse rate, never
# correctness.
STAGES=(
    "suite|no|the compiler test suite (zero UNCITED xfails is the bar)|$PY test_runner.py"
    "icebreadcrumb|no|an internal compiler error reports one located line|$PY tools/test_ice_breadcrumb.py"
    "lexdiff|no|the Saw lexer against sawc's, over every tracked .saw|$PY tools/lexdiff.py"
    "astdiff|no|every .saw dumps completely and byte-stably|$PY tools/astdiff.py"
    "astgraft|no|no pass stamps an AST attribute no class declares|$PY tools/test_ast_graft.py"
    "citations|no|the files nothing compiles: stale DF citations, committed conflict markers|$PY tools/check_citations.py"
    "forgetgate|no|every __saw_forget and M1/M3 stamp cites its deferral|$PY tools/test_forget_purge.py"
    "ircontract|no|-c embeds what hosted embeds; seam widths match rt/ABI.md|$PY tools/test_ir_contract.py"
    "preludegate|no|the import gate matches LANGUAGE_SPEC's module table|$PY tools/test_prelude_gate_doc.py"
    "stdtypes|no|two std files may each own one private type name (design 204)|$PY tools/test_std_private_type_names.py"
    "abidoc|no|rt/ABI.md describes exactly the frozen seam set|$PY tools/test_runtime_abi_doc.py"
    "bttable|no|the task-backtrace table against the frame layouts|$PY tools/test_bt_table.py"
    "fuzz|no|corpus-mutation fuzzing, one oracle: no ICE, no traceback|$PY tools/sawfuzz.py --quick"
    "corodiff|no|coroutine twin parity: suspending vs non-suspending|$PY tools/corodiff.py --quick"
    "bench|no|warehouse benchmark: checksums gate, timing reports|__BENCH__"
    "selfhostlex|no|the selfhost lexer's own tests compile and pass|__SELFHOSTLEX__"
    "reemit|yes|two compiles in ONE process emit identical unopt IR, opt IR and object|$PY tools/reemitdiff.py"
    "irdet|yes|IR determinism over the WHOLE corpus (not a sample)|__IRDET__"
    "gmgate|yes|ownership + concurrency oracles under Guard Malloc (macOS)|$PY tools/gmgate.py"
    "bootstrap|yes|Blade builds and tests Blade, stage0 through stage2|$PY tools/blade_bootstrap.py"
    "sos|yes|the SOS kernel + root server, booted under QEMU|$PY tools/sos_runner.py"
    "freestanding|yes|the freestanding feature suite, booted under QEMU|$PY tools/freestanding_runner.py"
)

usage() {
    echo "usage: tools/battery.sh [--quick] [--list] [stage ...]"
    echo
    echo "stages (a * marks one --quick skips):"
    for entry in "${STAGES[@]}"; do
        IFS='|' read -r name slow desc _cmd <<< "$entry"
        mark=" "
        [ "$slow" = "yes" ] && mark="*"
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

# irdet's harness is written in Saw (design 155), so it is built before it runs.
# `--all` and not the 40-example sample: design 141 found two nondeterministic
# emission orders that a sample had been walking past for weeks.
#
# The VERDICT comes from irdet's structured `--jsonl` records, never from `$?`
# (design 221 Part D). irdet's `main` suspends on every path, and until DF-220b
# was fixed a suspending `main` never propagated its return value — so this lane
# always read 0 and had never been able to fail. The status works now; reading
# the records anyway is the contract, because a gate should not depend on the
# bug it gates being fixed. `--plan` supplies the expected record count, which
# is what catches a run that stopped early rather than disagreeing. Design 220
# added a FOURTH record status, `invariant` (a reused suite artifact that a
# fresh recompile at its own recorded seed does not reproduce);
# `tools/irdet_verdict.py` fails on it exactly as it fails on `mismatch`, which
# is what keeps a cache bug from ever reading as green.
# DF-232m: irdetbin DRIVES sawc, so it needs `--python` — building it with $PY
# says nothing about the interpreter it then invokes, and its default is bare
# `python3`. From a worktree there is no ./.venv for that fallback to find, so
# every candidate failed to compile and the lane verified NOTHING.
run_irdet() {
    "$PY" sawc/sawc.py devtools/irdet/src/main.saw -o .build/irdetbin || return 1
    local records=".build/irdet-battery.jsonl"
    local planned
    rm -f "$records"
    planned=$(./.build/irdetbin --plan --all --python "$PY" | grep -c '\.saw$')
    ./.build/irdetbin --all --python "$PY" --jsonl "$records"
    "$PY" tools/irdet_verdict.py "$records" --expect "$planned"
}

# The bench harness is Saw too (the third devtool). Its CHECKSUMS gate — the
# benchmark is a behavioral pin — but its TIMING is report-only by design:
# battery numbers are trend-watching, and a slow machine is not a regression.
# See devtools/bench/warehouse/README.md and the tracker's "Measured
# performance" entry (Aug 10).
run_bench() {
    "$PY" sawc/sawc.py devtools/bench/warehouse/warehouse.saw -o .build/benchbin_warehouse || return 1
    "$PY" sawc/sawc.py devtools/bench/src/main.saw -o .build/benchdriver || return 1
    ./.build/benchdriver
}

# selfhost/lexer/tests was the one tree NO stage typechecked or ran (the
# Aug-10 coverage sweep found it: lexdiff/astdiff only lex/parse it, and no
# bootstrap-style runner exists for the package). Same exit-0-is-pass
# contract as `blade test`. The lexdiff stage builds the package's src/
# separately; this runs its TESTS.
run_selfhostlex() {
    local failed=0
    mkdir -p .build/selfhostlex
    for f in selfhost/lexer/tests/*.saw; do
        local name
        name="$(basename "$f" .saw)"
        if ! "$PY" sawc/sawc.py "$f" -o ".build/selfhostlex/$name"; then
            echo "selfhostlex: $name FAILED to compile"
            failed=$((failed + 1))
            continue
        fi
        if ! "./.build/selfhostlex/$name"; then
            echo "selfhostlex: $name FAILED at run"
            failed=$((failed + 1))
        fi
    done
    echo "selfhostlex: $(ls selfhost/lexer/tests/*.saw | wc -l | tr -d ' ') test(s), $failed failing"
    [ "$failed" -eq 0 ]
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
    if [ "$QUICK" = "1" ] && [ "$slow" = "yes" ] && [ ${#WANTED[@]} -eq 0 ]; then
        SKIPPED+=("$name")
        continue
    fi
    echo
    echo "=============================================================="
    echo "  $name — $desc"
    echo "=============================================================="
    stage_start=$(date +%s)
    if [ "$cmd" = "__IRDET__" ]; then
        run_irdet
    elif [ "$cmd" = "__BENCH__" ]; then
        run_bench
    elif [ "$cmd" = "__SELFHOSTLEX__" ]; then
        run_selfhostlex
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
    echo "battery: skipped by --quick: ${SKIPPED[*]}"
fi
if [ ${#FAILED[@]} -eq 0 ]; then
    echo "battery: $RAN stage(s) GREEN in ${elapsed}s"
    exit 0
fi
echo "battery: ${#FAILED[@]} of $RAN stage(s) FAILED in ${elapsed}s: ${FAILED[*]}"
echo
echo "Re-run one with its name: tools/battery.sh ${FAILED[0]}"
exit ${#FAILED[@]}
