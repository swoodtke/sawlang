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
 * `__saw_rt_pthread_create` passes a raw C function pointer (the spawn/offload
 * start routine, `void *(*)(void *)`) to pthread_create. Saw's surface has no
 * bare C function-pointer type (closures are fat pointers), so the start
 * routine cannot be forwarded from a Saw body. `tid` points at the task control
 * block's 8-byte pthread_t slot; `arg` is the routine's argument. The NULL attr
 * is what the wrapper exists to supply (Saw has no null-pointer literal at the
 * `pthread_t*`/attr level either). The mutex/cond-init + join wrappers ARE Saw
 * (sawc/rt/common/pthread.saw) — only this fn-pointer body stays here. */
void __saw_rt_pthread_create(void *tid, void *(*start)(void *), void *arg) {
    pthread_create((pthread_t *)tid, NULL, start, arg);
}
