"""The frozen `__saw_rt_*` runtime ABI symbol set (design 113 / 113b).

This is the single source of truth for the runtime-ABI symbol names — the
functions a RUNTIME implements and the compiler only DECLARES and CALLS
(sawc/rt/ABI.md). Both the typechecker (to allow exactly these names under
`--runtime-build`) and codegen (which declares them) import this set, so the
"valid export names" list the runtime-build reservation check reports is
literally the list the compiler declares. Freezing the set here is what lets a
runtime be a link-time swap (host_macos, host_linux, sos-hosted, kernel/none)
instead of compiler surgery.

Adding/removing a name here is an ABI change — it must be matched by codegen's
seam declarations and by every runtime implementation.
"""

# The `__saw_rt_*` names, grouped as in ABI.md. Order is documentation only;
# membership is what matters.
RUNTIME_ABI_SYMBOLS = frozenset({
    # Allocation / output / panic
    "__saw_rt_alloc",
    "__saw_rt_dealloc",
    # Hosted-only test facility (design 123): arm an allocation budget so an
    # OOM path can be driven deterministically. std never calls it.
    "__saw_rt_alloc_deny_after",
    "__saw_rt_write",
    "__saw_rt_panic",
    # Time (design 180 replaced the millisecond seam with this one: a u64
    # nanosecond request, chunked to libc's 32-bit microsecond bound inside the
    # body, so no span a caller can spell wraps into a shorter one).
    "__saw_rt_sleep_ns",
    "__saw_rt_clock_monotonic_nanos",
    "__saw_rt_unix_timestamp_secs",
    # Errors (design 117: the errno accessors are gone; the host errno ->
    # portable SysError tag mapping lives behind this one seam)
    "__saw_rt_last_syserror",
    # Sockets
    "__saw_rt_set_nonblocking",
    "__saw_rt_sin_set_family",
    # Status-carrying network ops (design 117)
    "__saw_rt_tcp_listen",
    "__saw_rt_tcp_local_port",
    "__saw_rt_tcp_accept",
    "__saw_rt_tcp_connect_start",
    "__saw_rt_tcp_connect_check",
    "__saw_rt_tcp_read",
    "__saw_rt_tcp_write",
    # Hostname resolution (design 184). The ONE seam whose ABI.md entry states a
    # blocking contract: it is unbounded by nature, so std declares it
    # `extern blocking` and every call is offloaded to a worker thread.
    "__saw_rt_resolve_ipv4",
    # Status-carrying filesystem / environment ops (design 117)
    "__saw_rt_fs_unlink",
    "__saw_rt_fs_rename",
    "__saw_rt_fs_mkdir",
    "__saw_rt_fs_rmdir",
    "__saw_rt_fs_chdir",
    # Status-carrying file I/O (design 132 unit G). These were bare libc calls
    # in std, where the failure CAUSE was unreadable — errno is runtime-internal
    # — so `File.open`/`read`/`write` could only answer `None`. Additive, like
    # the dirent projection below.
    "__saw_rt_fs_open",
    "__saw_rt_fs_read",
    "__saw_rt_fs_write",
    "__saw_rt_fs_lseek",
    "__saw_rt_fs_opendir",
    # `struct dirent` name projection — the one OS-divergent part of a readdir
    # walk (design 122 unit F)
    "__saw_rt_fs_dirent_name",
    "__saw_rt_env_set",
    "__saw_rt_env_unset",
    # Process spawn (design 122 unit C): real argv spawn, no shell anywhere.
    # The `_env` twin (design 155) carries per-child environment overrides —
    # only the runtime can reach the process environment.
    "__saw_rt_proc_spawn",
    "__saw_rt_proc_spawn_env",
    "__saw_rt_proc_read_stdout",
    # Design 182 made the CHILD WAIT zero-thread: `try_wait` polls (WNOHANG) and
    # `wait_fd` hands back a descriptor to park on, so neither `Command.run` nor
    # `Command.output` ever sits in `waitpid`. `proc_exit_fd` is the one
    # host-divergent piece (kqueue EVFILT_PROC vs pidfd_open); `proc_release` is
    # the cancellation exit. The v1 blocking reap `__saw_rt_proc_wait` was
    # REMOVED by design 187 unit 11, when its last caller went cooperative.
    "__saw_rt_proc_exit_fd",
    "__saw_rt_proc_wait_fd",
    "__saw_rt_proc_try_wait",
    "__saw_rt_proc_release",
    # Cooperative-scheduler fairness (design 89-c)
    "__saw_rt_op_budget_tick",
    "__saw_rt_op_budget_reset",
    # The IO reactor (designs 76 / 91 / 102; instance-based by design 117)
    "__saw_rt_reactor_create",
    "__saw_rt_reactor_register",
    # DF-134a (design 147, user-approved into the frozen set): drop an armed
    # registration that never fired, so its token cannot outlive the frame.
    "__saw_rt_reactor_unregister",
    "__saw_rt_reactor_poll",
    "__saw_rt_reactor_wake",
    "__saw_rt_reactor_destroy",
    # Threads (design 21; consolidated to spawn/join by design 117)
    "__saw_rt_thread_spawn",
    "__saw_rt_thread_join",
    "__saw_rt_pthread_mutex_init_default",
    "__saw_rt_pthread_cond_init_default",
    # Blocking-extern offload (design 103)
    "__saw_rt_offload_start",
    "__saw_rt_offload_done",
    "__saw_rt_offload_pipe_fd",
    "__saw_rt_offload_take",
    "__saw_rt_blocking_sleep",
    # Program arguments (design 81 CI rider)
    "__saw_rt_get_argc",
    "__saw_rt_get_argv",
})


def valid_export_names_message() -> str:
    """A stable, sorted rendering of the ABI set for the reservation error's
    typo-protection hint under `--runtime-build`."""
    return ", ".join(sorted(RUNTIME_ABI_SYMBOLS))


# ---------------------------------------------------------------------------
# Signatures (design 149 unit c)
#
# ABI.md carries a C signature for every seam. Those signatures are the contract
# a runtime implements, and until now nothing checked an implementation against
# them: a seam written with the wrong arity or a 32-bit result where the ABI says
# 64 linked fine and misbehaved at run time, on the ONE boundary in the language
# whose whole purpose is to be stable.
#
# The signatures are read out of ABI.md itself rather than transcribed here, so
# the document IS the contract and cannot drift from what the compiler enforces.
# `test_runtime_abi_doc.py` checks the other direction — that the document names
# exactly the frozen symbol set.
# ---------------------------------------------------------------------------

import os
import re
from typing import Dict, Optional, Tuple

_ABI_DOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rt", "ABI.md")

# A signature inside backticks: `name(params) -> ret`, with an optional trailing
# parenthesized gloss on the return (`-> word  (0/-1)`).
_SIG_RE = re.compile(r"`(__saw_rt_[A-Za-z0-9_]+)\(([^`]*)\)\s*->\s*([^`]+)`")

# ABI type vocabulary -> the machine class the C ABI actually distinguishes.
# Every pointer and every `word` is pointer-width, so they share a class: the
# check is about ARITY and WIDTH, which is what a mismatch can actually corrupt.
# `Int64` stays distinct from `word` because they differ on a 32-bit target,
# which is exactly where a wrong one would bite.
_ABI_CLASSES = {
    "void": "void",
    "!": "noreturn",
    "i32": "i32",
    "int64": "i64",
    "i64": "i64",
    "word": "word",
    "ptr": "word",
}

_SIGNATURE_CACHE: Optional[Dict[str, Tuple[Tuple[str, ...], str]]] = None


def _abi_class(spelling: str) -> str:
    """The machine class of one ABI type spelling from the document."""
    text = spelling.strip()
    # Drop a trailing prose gloss: `word  (0/-1)`, `! (noreturn)`, `ptr (handle)`.
    text = text.split('(')[0].strip() if not text.startswith('void*') else text
    if not text:
        return "void"
    if text.endswith('*') or text.startswith('void*'):
        return "word"          # every pointer spelling is pointer-width
    return _ABI_CLASSES.get(text.lower(), text.lower())


def abi_signatures() -> Dict[str, Tuple[Tuple[str, ...], str]]:
    """`{symbol: (param classes, return class)}` parsed from rt/ABI.md.

    Cached: one compile asks once per exported seam. A symbol the document
    describes more than once keeps its FIRST signature, and a symbol it does not
    describe is simply absent — the caller then checks nothing, which is the
    right behavior for a document that has fallen behind rather than a reason to
    refuse a build.
    """
    global _SIGNATURE_CACHE
    if _SIGNATURE_CACHE is not None:
        return _SIGNATURE_CACHE

    found: Dict[str, Tuple[Tuple[str, ...], str]] = {}
    try:
        with open(_ABI_DOC, 'r') as f:
            text = f.read()
    except OSError:
        _SIGNATURE_CACHE = found
        return found

    for match in _SIG_RE.finditer(text):
        name, params, ret = match.group(1), match.group(2), match.group(3)
        if name in found:
            continue
        classes = []
        for part in params.split(','):
            part = part.strip()
            if not part:
                continue
            # `size: word` — the name is documentation, the type is the contract.
            spelling = part.split(':', 1)[1] if ':' in part else part
            classes.append(_abi_class(spelling))
        found[name] = (tuple(classes), _abi_class(ret))

    _SIGNATURE_CACHE = found
    return found


def render_abi_signature(name: str) -> Optional[str]:
    """The documented signature of `name` as a readable string, for diagnostics."""
    sig = abi_signatures().get(name)
    if sig is None:
        return None
    params, ret = sig
    return f"{name}({', '.join(params) or ''}) -> {ret}"
