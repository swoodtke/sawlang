#!/bin/sh
# Per-clone git setup, run once in each clone (worktrees share its config):
#
#   tools/git_setup.sh
#
# Defines the keep-main merge driver that .gitattributes names: the driver
# command `true` keeps %A, which is main's side on a rebase. A merge driver
# lives in git config, never in the tree, so a clone without this falls back
# to an ordinary text merge. Both keys are set together because a half-set
# driver is worse than none: with `merge.keep-main.name` and no `.driver`,
# every rebase or `git apply --3way` touching such a file dies with "custom
# merge driver keep-main lacks command line" (exit 128).
#
# Writes only the clone's own config, never the global or system one, and
# setting the same values again changes nothing.
set -eu

repo="$(cd "$(dirname "$0")/.." && pwd)"
git -C "$repo" config --local merge.keep-main.name "keep main's version of a derived file"
git -C "$repo" config --local merge.keep-main.driver true
