#!/bin/sh
# The machine-wide suite lock (CLAUDE.md, "THE SUITE LOCK"): a directory whose
# mkdir is the acquisition, holding a `holder` file that names who took it.
#
#   tools/suite_lock.sh acquire [--pid PID] COMMAND...   wait for the lock, then take it
#   tools/suite_lock.sh release                          give it back
#   tools/suite_lock.sh status                           who holds it, if anyone
#
# acquire says who holds the lock when it is busy at entry, prints a heartbeat
# while it waits and the total wait once it holds it, so a run queued behind a
# long gate says why it is silent. PID is the process the lock belongs to, by
# default the calling shell. A waiter whose PID dies stops waiting without the
# lock, so a signal that kills only its parent cannot leave it to take the lock
# for nobody. That is a waiter declining for itself: a caller that exits while
# holding the lock leaves a dead pid behind, so a dead pid alone never proves
# someone else's lock stale. A lock directory without a holder file works the
# same and reads as an unknown holder.
#
# SAW_SUITE_LOCK names another lock directory, SAW_SUITE_LOCK_HEARTBEAT and
# SAW_SUITE_LOCK_POLL the heartbeat and polling intervals in seconds
# (tools/test_suite_lock.py).
set -u

LOCK="${SAW_SUITE_LOCK:-/private/tmp/claude-$(id -u)/saw-suite-lock}"
HOLDER="$LOCK/holder"
HEARTBEAT="${SAW_SUITE_LOCK_HEARTBEAT:-300}"
POLL="${SAW_SUITE_LOCK_POLL:-15}"

say() { echo "suite lock: $*"; }

usage() {
    echo "usage: tools/suite_lock.sh acquire [--pid PID] COMMAND... | release | status" >&2
    exit 2
}

duration() {
    s=$1
    if [ "$s" -ge 3600 ]; then
        printf '%dh %dm %ds' $((s / 3600)) $((s % 3600 / 60)) $((s % 60))
    elif [ "$s" -ge 60 ]; then
        printf '%dm %ds' $((s / 60)) $((s % 60))
    else
        printf '%ds' "$s"
    fi
}

# BSD date first (macOS, where the server runs), then GNU date.
utc() {
    date -u -r "$1" '+%Y-%m-%d %H:%M:%S UTC' 2>/dev/null \
        || date -u -d "@$1" '+%Y-%m-%d %H:%M:%S UTC'
}

mtime() {
    stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null
}

# kill -0 also succeeds on a zombie, which is what a killed parent stays until
# its own parent reaps it, so ps rules that out where it can run; a sandbox may
# refuse ps, and then kill -0 alone decides.
alive() {
    kill -0 "$1" 2>/dev/null || return 1
    case "$(ps -o stat= -p "$1" 2>/dev/null)" in
        *Z*) return 1 ;;
    esac
    return 0
}

field() {
    sed -n "s/^$1: //p" "$HOLDER" 2>/dev/null | head -n 1
}

# One phrase naming the holder and since when. The holder can release between
# the caller's failed mkdir and this read, so every field may come back empty.
describe() {
    if [ -f "$HOLDER" ]; then
        since=$(field started | sed 's/ .*//')
        what="pid $(field pid) ($(field command), in $(field cwd))"
    else
        since=$(mtime "$LOCK")
        what="an unknown holder (no holder file)"
    fi
    if [ -n "$since" ]; then
        echo "$what since $(utc "$since"), $(duration $(($(date +%s) - since))) ago"
    else
        echo "$what"
    fi
}

abandon() {
    if [ "$took" = 1 ]; then
        rm -f "$HOLDER" "$LOCK/.holder.$$"
        rmdir "$LOCK" 2>/dev/null
        say "released at once: a signal arrived before the caller held it"
    fi
    exit "$1"
}

acquire() {
    pid=$PPID
    if [ "${1:-}" = "--pid" ]; then
        [ $# -ge 2 ] || usage
        pid=$2
        shift 2
    fi
    [ $# -gt 0 ] || usage
    parent=$(dirname "$LOCK")
    mkdir -p "$parent" || exit 2
    # Without this, a lock that can never be created reads as one held forever.
    if [ ! -w "$parent" ]; then
        say "cannot create $LOCK: $parent is not writable"
        exit 2
    fi
    start=$(date +%s)
    busy=0
    # A signal between the mkdir and this script's exit lands before the
    # caller has a trap that would release the lock, so the lock goes with it.
    took=0
    trap 'abandon 129' HUP
    trap 'abandon 130' INT
    trap 'abandon 143' TERM
    if mkdir "$LOCK" 2>/dev/null; then
        took=1
    else
        busy=1
        say "held by $(describe); waiting"
        beat=$start
        until mkdir "$LOCK" 2>/dev/null; do
            if ! alive "$pid"; then
                say "stopped waiting: pid $pid, which it waited for, is gone; the lock was not taken"
                exit 1
            fi
            sleep "$POLL"
            now=$(date +%s)
            if [ $((now - beat)) -ge "$HEARTBEAT" ]; then
                beat=$now
                say "still waiting after $(duration $((now - start))); held by $(describe)"
            fi
        done
        took=1
    fi
    now=$(date +%s)
    # Written aside and renamed, so a reader never sees half a holder file.
    printf 'pid: %s\ncommand: %s\ncwd: %s\nstarted: %s (%s)\n' \
        "$pid" "$*" "$(pwd)" "$now" "$(utc "$now")" > "$LOCK/.holder.$$"
    mv "$LOCK/.holder.$$" "$HOLDER"
    # The owner can die between the last poll and the mkdir; nothing would
    # ever release a lock taken for it.
    if ! alive "$pid"; then
        rm -f "$HOLDER"
        rmdir "$LOCK"
        took=0
        say "released at once: pid $pid, which it waited for, is gone"
        exit 1
    fi
    if [ "$busy" = 1 ]; then
        say "acquired after waiting $(duration $((now - start)))"
    else
        say "acquired; it was free"
    fi
}

release() {
    held=""
    if [ -f "$HOLDER" ]; then
        since=$(field started | sed 's/ .*//')
        [ -n "$since" ] && held=" after holding it $(duration $(($(date +%s) - since)))"
    fi
    rm -f "$HOLDER" "$LOCK"/.holder.*
    rmdir "$LOCK" || exit 1
    say "released$held"
}

status() {
    if [ -d "$LOCK" ]; then
        say "held by $(describe)"
    else
        say "free"
    fi
}

case "${1:-}" in
    acquire) shift; acquire "$@" ;;
    release) [ $# -eq 1 ] || usage; release ;;
    status) [ $# -eq 1 ] || usage; status ;;
    *) usage ;;
esac
