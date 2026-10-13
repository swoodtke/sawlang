#!/bin/sh
# The sawtracker patch gate's entry point: `.sawtracker/tests.json` runs
# `./build.sh test --changed-since HEAD^` on every submitted patch, in the
# server's own clone, where HEAD is the applied patch and HEAD^ its base. Also
# fine to run by hand:
#
#   ./build.sh test                        everything
#   ./build.sh test --changed-since REV    what the change since REV needs
#   ./build.sh test --diff FILE            what a patch file needs
#   ./build.sh test ... --dry-run          print that decision, run nothing
#
# tools/patch_gate.py decides which suites a change needs and runs them. This
# script bootstraps .venv when absent (SAW_PYTHON names an interpreter to use
# instead, as from a worktree) and holds the machine-wide suite lock around the
# run through tools/suite_lock.sh, so a server-side patch test never overlaps a
# local suite.
set -e

cd "$(dirname "$0")"

case "${1:-test}" in
  test) if [ $# -gt 0 ]; then shift; fi ;;
  *) echo "usage: ./build.sh test [--changed-since REV | --diff FILE] [--dry-run]" >&2
     exit 2 ;;
esac

# A dry run reads git and nothing else, so it needs neither the venv nor the lock.
for arg in "$@"; do
    if [ "$arg" = "--dry-run" ]; then
        exec "${SAW_PYTHON:-python3}" tools/patch_gate.py "$@"
    fi
done

if [ -n "${SAW_PYTHON:-}" ]; then
    PY="$SAW_PYTHON"
else
    if [ ! -x .venv/bin/python ]; then
        python3 -m venv .venv
        .venv/bin/python -m pip install --quiet --upgrade pip
        .venv/bin/python -m pip install --quiet -r sawc/requirements.txt
    fi
    PY=.venv/bin/python
fi

# The lock's own messages say who holds it and how long the wait took; the
# gate's summary reports that wait apart from the test time.
LOCK_START=$(date +%s)
sh tools/suite_lock.sh acquire --pid $$ "./build.sh test $*"
# A signal exits with 128 + its number, so the server can tell an interrupted
# run from a failed one; the exit trap releases the lock either way. Until
# these traps exist a signal would end this shell holding the lock, so nothing
# runs between the acquire and them (tools/test_suite_lock.py).
trap 'sh tools/suite_lock.sh release' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
SAW_GATE_LOCK_WAIT=$(($(date +%s) - LOCK_START))
export SAW_GATE_LOCK_WAIT

"$PY" tools/patch_gate.py "$@"
