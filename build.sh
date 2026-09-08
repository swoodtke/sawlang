#!/bin/sh
# The sawtracker patch gate's entry point: `.sawtracker/tests.json` runs
# `./build.sh test` on every submitted patch, in the server's own clone.
# Also fine to run by hand. Bootstraps .venv when absent, then runs the
# compiler's per-commit gate — full suite + the freestanding feature
# suite, both arches — under the machine-wide suite lock (TESTING.md)
# so a server-side patch test never overlaps a local suite run.
set -e

cd "$(dirname "$0")"

case "${1:-test}" in
  test) ;;
  *) echo "usage: ./build.sh test" >&2; exit 2 ;;
esac

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -r sawc/requirements.txt
fi

LOCK="/private/tmp/claude-$(id -u)/saw-suite-lock"
mkdir -p "$(dirname "$LOCK")"
until mkdir "$LOCK" 2>/dev/null; do sleep 15; done
trap 'rmdir "$LOCK"' EXIT INT TERM

.venv/bin/python test_runner.py
.venv/bin/python tools/freestanding_runner.py
