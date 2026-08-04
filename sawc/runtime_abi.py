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
    "__saw_rt_write",
    "__saw_rt_panic",
    # Time
    "__saw_rt_sleep_ms",
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
    # Status-carrying filesystem / environment ops (design 117)
    "__saw_rt_fs_unlink",
    "__saw_rt_fs_rename",
    "__saw_rt_fs_mkdir",
    "__saw_rt_fs_rmdir",
    "__saw_rt_fs_chdir",
    "__saw_rt_env_set",
    "__saw_rt_env_unset",
    # Cooperative-scheduler fairness (design 89-c)
    "__saw_rt_op_budget_tick",
    "__saw_rt_op_budget_reset",
    # The IO reactor (designs 76 / 91 / 102; instance-based by design 117)
    "__saw_rt_reactor_create",
    "__saw_rt_reactor_register",
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
