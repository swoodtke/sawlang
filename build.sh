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
# run (TESTING.md), so a server-side patch test never overlaps a local suite.
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

LOCK="/private/tmp/claude-$(id -u)/saw-suite-lock"
mkdir -p "$(dirname "$LOCK")"
until mkdir "$LOCK" 2>/dev/null; do sleep 15; done
trap 'rmdir "$LOCK"' EXIT INT TERM

"$PY" tools/patch_gate.py "$@"
