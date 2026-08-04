/* The Saw runtime C shim (design 113b).
 *
 * The `__saw_rt_*` runtime ABI (sawc/rt/ABI.md) is authored in Saw under
 * `--runtime-build` — EXCEPT the three bodies below, each blocked by a specific
 * Saw FFI gap tracked as a DF-finding. Every one of these shrinks to Saw the day
 * its language feature lands (the three future designs queued in designs/todo.md
 * under "FFI gaps blocking a pure-Saw runtime"). Keep this file as small as the
 * gaps require, and keep each body annotated with its DF number.
 *
 * This is the HOSTED (macOS/Linux) shim; a kernel/sos-hosted runtime supplies
 * its own. Compiled with clang by sawc/rt_build.py.
 */

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <fcntl.h>
#include <unistd.h>

/* ---- DF-113a: no extern C global ---------------------------------------
 * `__saw_rt_write`/`_panic` route through C stdio's `stdout` FILE* (spelled
 * `__stdoutp` on macOS, `stdout` on Linux — the C name `stdout` resolves to
 * either). Saw has no `extern static` / extern-global syntax, so it cannot
 * name `stdout`; and switching to a raw `write(2)` would reorder `print`
 * output against the still-`printf`-based Float path (fwrite + fflush keeps
 * int/float/string prints on ONE buffered stream, program order preserved —
 * the ABI.md ordering guarantee). Hence C.
 */
void __saw_rt_write(const char *ptr, size_t len) {
    fwrite(ptr, 1, len, stdout);
    fflush(stdout);
}

/* The infallible-tier panic sink (design 19): emit the message via
 * __saw_rt_write, then abort(). noreturn. (Rides on the same DF-113a `stdout`
 * dependency as __saw_rt_write.) */
__attribute__((noreturn))
void __saw_rt_panic(const char *msg, size_t len) {
    __saw_rt_write(msg, len);
    abort();
}

/* ---- DF-113b: no C function-pointer type -------------------------------
 * `__saw_rt_thread_spawn` passes a raw C function pointer (the spawn/offload
 * start routine, `void *(*)(void *)`) to pthread_create. Saw's surface has no
 * bare C function-pointer type (closures are fat pointers), so the start
 * routine cannot be forwarded from a Saw body. `entry` is the start routine,
 * `env` its argument; the NULL attr is what the wrapper exists to supply (Saw
 * has no null-pointer literal at the attr level either). design 117: RETURN the
 * OS thread handle (`pthread_t`, pointer-sized on both hosts) as a word — spawn
 * codegen stores it into the control block's 8-byte slot, and
 * `__saw_rt_thread_join` takes it back by value. The mutex/cond-init + join
 * wrappers ARE Saw (sawc/rt/common/pthread.saw) — only this fn-pointer body
 * stays here. */
long __saw_rt_thread_spawn(void *(*entry)(void *), void *env) {
    pthread_t t;
    pthread_create(&t, NULL, entry, env);
    return (long)t;
}

/* ---- DF-113c: no variadic extern ---------------------------------------
 * Set O_NONBLOCK on `fd`. `fcntl` is VARIADIC in C — `int fcntl(int, int, ...)`
 * — and the F_SETFL flag word is the variadic argument. On arm64 (Apple
 * Silicon) a fixed-arity declaration passes that argument in a register the
 * variadic callee reads off the STACK, so it reads garbage (a code-layout-
 * sensitive heisenbug: nonblocking sockets that intermittently block). Saw
 * extern declarations have no `...`, so this call must be C. F_GETFL/F_SETFL/
 * O_NONBLOCK come from <fcntl.h> (the per-OS values C already knows). Returns
 * 0 on success, -1 on the F_GETFL failure — the design-84 ABI. */
long __saw_rt_set_nonblocking(long fd) {
    int flags = fcntl((int)fd, F_GETFL, 0);
    if (flags < 0) return -1;
    fcntl((int)fd, F_SETFL, flags | O_NONBLOCK);
    return 0;
}

/* ---- DF-113b: the blocking-extern offload thread thunk ------------------
 * The offload seams `__saw_rt_offload_start/done/pipe_fd/take` are authored in
 * Saw (sawc/rt/common/offload.saw); this thunk is the ONE piece that must be C
 * — it CALLS a raw C function pointer (`job->fn`, a `long(long)` blocking
 * extern), which Saw cannot express (DF-113b). It touches ONLY its own job + the
 * pipe write end (the hazard discipline): run fn(arg), store the result,
 * PUBLISH `done` (atomic release) after the store, then write one byte to the
 * job's self-pipe. `__saw_offload_thread_ptr` hands the Saw `offload_start` the
 * thunk's address (Saw cannot name a C function pointer either), which it
 * forwards to __saw_rt_thread_spawn.
 *
 * The struct layout MUST match `struct Job` in offload.saw (sizeof == 48, guarded
 * by a static_assert there): { i64 fn, arg, result, done; i32 pipe_r, pipe_w;
 * i64 thread }. `done` is accessed atomically on both sides. */
struct saw_offload_job {
    long fn;
    long arg;
    long result;
    long done;      /* atomic */
    int  pipe_r;
    int  pipe_w;
    long thread;    /* pthread_t slot */
};

static void *__saw_offload_thread(void *jobp) {
    struct saw_offload_job *job = (struct saw_offload_job *)jobp;
    long (*thunk)(long) = (long (*)(long))job->fn;
    long res = thunk(job->arg);
    job->result = res;
    __atomic_store_n(&job->done, 1L, __ATOMIC_RELEASE);
    unsigned char one = 1;
    ssize_t w = write(job->pipe_w, &one, 1);
    (void)w;
    return NULL;
}

/* The offload thunk's address as an opaque pointer (Saw has no C function-
 * pointer type). offload_start forwards it to __saw_rt_thread_spawn. */
void *__saw_offload_thread_ptr(void) {
    return (void *)__saw_offload_thread;
}
