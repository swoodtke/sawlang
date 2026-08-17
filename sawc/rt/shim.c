/* The Saw runtime C shim (design 113b).
 *
 * The `__saw_rt_*` runtime ABI (sawc/rt/ABI.md) is authored in Saw under
 * `--runtime-build` — EXCEPT the bodies below, each blocked by a specific
 * Saw FFI gap tracked as a DF-finding. Every one of these shrinks to Saw the day
 * its language feature lands (the three future designs queued in designs/todo.md
 * under "FFI gaps blocking a pure-Saw runtime"). Keep this file as small as the
 * gaps require, and keep each body annotated with its DF number.
 *
 * This is the HOSTED (macOS/Linux) shim; a kernel/sos-hosted runtime supplies
 * its own. Compiled with clang by sawc/rt_build.py.
 *
 * `_GNU_SOURCE` before the first include, because glibc hides `EAI_NODATA`
 * behind `__USE_GNU` — and hiding it is not the same as not having it: glibc
 * RETURNS EAI_NODATA (resolving "" is one way), so without this the
 * `#ifdef EAI_NODATA` arm of `__saw_gai_tag` compiles out and the code the
 * resolver actually returned falls through to `Other` instead of `NotFound`.
 * macOS defines the feature macro away, so this costs nothing there.
 */
#define _GNU_SOURCE

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

/* ---- DF-113a: no C macro (design 155) ----------------------------------
 * The `open(2)` flag bits are PER-HOST macros, and std had them written out as
 * decimal literals — the LINUX values, used on both hosts. On macOS that made
 * `File.create` mean `O_WRONLY | O_ASYNC | O_CREAT` (no `O_TRUNC`: writing 3
 * bytes over a 30-byte file left a 30-byte file) and `File.open_append` mean
 * `O_WRONLY | O_ASYNC | O_TRUNC` (no `O_CREAT`: appending to a missing file
 * failed with ENOENT, and appending to a present one truncated it).
 *
 * So `__saw_rt_fs_open` takes a PORTABLE open MODE now (rt/ABI.md) and this
 * translates it, in the one language that can see <fcntl.h>. Saw cannot name a
 * C macro any more than it can name a C global, and a table of decimal literals
 * is exactly the bug: it cannot be right on two hosts at once. Keep the mode
 * numbering in step with `OpenMode` in sawc/std/file.saw. */
#include <fcntl.h>

long __saw_open_flags(long mode) {
    switch (mode) {
    case 0: return O_RDONLY;
    case 1: return O_WRONLY | O_CREAT | O_TRUNC;
    case 2: return O_WRONLY | O_CREAT | O_APPEND;
    default: return -1;
    }
}

/* ---- DF-113a: no C macro, no per-host struct layout (design 184) --------
 * `__saw_rt_resolve_ipv4` walks the `struct addrinfo` list getaddrinfo(3)
 * returns. The walk, the hints, the lifetime (`freeaddrinfo`) and the error
 * mapping are all Saw (sawc/rt/common/os_ops.saw); these three projections are
 * C because they are header facts a Saw body cannot see:
 *
 *   - `struct addrinfo`'s FIELD ORDER diverges. glibc declares `ai_addr` ahead
 *     of `ai_canonname`; macOS declares them the other way round, so `ai_addr`
 *     sits at a different offset on each host. A hardcoded offset cannot be
 *     right on both — exactly the design-122 `d_name` bug, which shipped.
 *   - the `EAI_*` failure codes are per-host macros disagreeing in value AND in
 *     sign (`EAI_NONAME` is 8 on macOS and -2 on glibc), the same reason the
 *     `O_*` bits above are translated here rather than written out in std.
 */
#include <netdb.h>
#include <netinet/in.h>
#include <sys/socket.h>

/* The next entry in the list, or NULL at its end. */
const void *__saw_ai_next(const void *entry) {
    return (const void *)((const struct addrinfo *)entry)->ai_next;
}

/* The entry's IPv4 address in network byte order, written to `out`. Returns 1
 * when the entry is an AF_INET address (and `out` was written), 0 when it is
 * not — a status rather than a sentinel, because 0.0.0.0 is representable. */
long __saw_ai_ipv4(const void *entry, unsigned int *out) {
    const struct addrinfo *ai = (const struct addrinfo *)entry;
    if (ai->ai_family != AF_INET || ai->ai_addr == NULL) return 0;
    *out = ((const struct sockaddr_in *)(const void *)ai->ai_addr)->sin_addr.s_addr;
    return 1;
}

/* A getaddrinfo(3) failure code as a portable SysError tag (rt/ABI.md), or 0
 * for EAI_SYSTEM — whose cause is in errno, which the Saw caller reads with
 * `__saw_rt_last_syserror()` on the next line. `EAI_AGAIN` is a temporary
 * resolver failure, which is what the WouldBlock tag (EAGAIN, "resource
 * temporarily unavailable") means; the rest collapse into NotFound / Exhausted
 * / Invalid / Other. */
long __saw_gai_tag(long code) {
    int rc = (int)code;
    if (rc == EAI_SYSTEM) return 0;                          /* ask errno */
    if (rc == EAI_NONAME) return 10;                         /* NotFound */
#ifdef EAI_NODATA
    if (rc == EAI_NODATA) return 10;                         /* NotFound */
#endif
    if (rc == EAI_AGAIN) return 1;                           /* WouldBlock */
    if (rc == EAI_MEMORY) return 15;                         /* Exhausted */
    if (rc == EAI_FAMILY || rc == EAI_SOCKTYPE
        || rc == EAI_SERVICE || rc == EAI_BADFLAGS) return 14;  /* Invalid */
    return 16;                                               /* Other */
}

/* ---- DF-113a: no extern C global (design 155) ---------------------------
 * The child of `__saw_rt_proc_spawn_env` gets its environment by having the
 * process-wide `environ` point at the merged array before `execvp` — which is
 * how a portable `execvpe` is written, and the only way to keep PATH search
 * (`execvp` takes the new image's environment from `environ`, per POSIX) while
 * still choosing that environment. Both halves are a pointer load and a pointer
 * store, so the SET half is async-signal-safe and legal in the window between
 * fork and exec; the merge itself runs in the PARENT, before the fork, where
 * malloc is allowed (rt/common/proc.saw). Saw has no extern-global syntax, so
 * naming `environ` is C — the same gap that keeps `stdout` here.
 *
 * macOS exports `environ` to executables but the supported spelling is
 * `_NSGetEnviron()`, which works in a bundle or dylib too; Linux has the
 * variable itself. */
#ifdef __APPLE__
#include <crt_externs.h>
#define SAW_ENVIRON (*_NSGetEnviron())
#else
extern char **environ;
#define SAW_ENVIRON environ
#endif

char **__saw_environ_get(void) {
    return SAW_ENVIRON;
}

void __saw_environ_set(char **env) {
    SAW_ENVIRON = env;
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
 * — it CALLS a raw C function pointer (`job->fn`, a `long(long)` entry), which
 * Saw cannot express (DF-113b). It touches ONLY its own job + the pipe write end
 * (the hazard discipline): run fn(args), store the result, PUBLISH `done`
 * (atomic release) after the store, then write one byte to the job's self-pipe.
 * `__saw_offload_thread_ptr` hands the Saw `offload_start` the thunk's address
 * (Saw cannot name a C function pointer either), which it forwards to
 * __saw_rt_thread_spawn.
 *
 * design 183: `job->fn` is NOT the user's blocking extern — it is a thunk the
 * COMPILER synthesized for that extern, and `job->args` points at the call's
 * argument slots, which the thunk reads back at their declared types before
 * making the real call. That keeps the C ABI in the compiler's ordinary extern
 * lowering, so any signature the C-ABI whitelist admits offloads and this file
 * needs no arity knowledge at all.
 *
 * The struct layout MUST match `struct Job` in offload.saw (sizeof == 48, guarded
 * by a static_assert there): { i64 fn, args, result, done; i32 pipe_r, pipe_w;
 * i64 thread }. `done` is accessed atomically on both sides. */
struct saw_offload_job {
    long fn;
    long args;
    long result;
    long done;      /* atomic */
    int  pipe_r;
    int  pipe_w;
    long thread;    /* pthread_t slot */
};

static void *__saw_offload_thread(void *jobp) {
    struct saw_offload_job *job = (struct saw_offload_job *)jobp;
    long (*thunk)(long) = (long (*)(long))job->fn;
    long res = thunk(job->args);
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

/* ---- DF-186c: no 32-bit atomics, no variadic extern (design 186) --------
 * `__saw_rt_lock_acquire` / `_release` — the one-word lock behind the inline
 * `Mutex<T>` (rt/ABI.md). The MACOS body is Saw (sawc/rt/host_macos/lock.saw):
 * it is two `os_unfair_lock` calls, which Saw can express. The LINUX body is a
 * futex, and it is here because a futex needs two things Saw has not got:
 *
 *   - ATOMICS ON A 32-BIT WORD REACHED THROUGH A POINTER. A futex word is a
 *     `uint32_t` the kernel compares, and `Atomic<T>` is `Atomic<Int>` in v1
 *     with no spelling for "atomically operate on this pointee".
 *   - a VARIADIC extern. glibc's is `long syscall(long, ...)`, and a Saw
 *     extern declaration has no `...` — the same DF-113c gap `fcntl` sits in.
 *
 * Both shrink this body to Saw the day either feature lands.
 *
 * The word is the low four bytes of the platform `Int` std hands over (both
 * hosted targets are little-endian, which is what lets one Saw field be a
 * 4-byte lock on macOS and a 4-byte futex word here). Drepper's three-state
 * protocol: 0 unlocked, 1 locked with nobody waiting, 2 locked with at least
 * one waiter — so an UNCONTENDED acquire is one compare-exchange and an
 * uncontended release is one store, and only a real collision enters the
 * kernel. `FUTEX_*_PRIVATE` skips the shared-mapping bookkeeping, which is
 * right for a lock inside one address space.
 *
 * Zero is unlocked, which is the property the whole unit turns on: a `static M:
 * Mutex<T>` with no initializer is a valid unlocked mutex on both hosts.
 */
#ifdef __linux__
#include <linux/futex.h>
#include <sys/syscall.h>
#include <limits.h>
#include <stdint.h>

static void saw_futex_wait(uint32_t *word, uint32_t expect) {
    syscall(SYS_futex, word, FUTEX_WAIT_PRIVATE, expect, NULL, NULL, 0);
}

static void saw_futex_wake_one(uint32_t *word) {
    syscall(SYS_futex, word, FUTEX_WAKE_PRIVATE, 1, NULL, NULL, 0);
}

void __saw_rt_lock_acquire(void *state) {
    uint32_t *word = (uint32_t *)state;
    uint32_t expected = 0;
    if (__atomic_compare_exchange_n(word, &expected, 1u, 0,
                                    __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) {
        return;   /* uncontended: no syscall */
    }
    /* Contended. Claim the lock as CONTENDED before sleeping so the holder
     * knows a wake is owed; re-reading through the swap is what closes the race
     * where it released between our failed exchange and this point. */
    while (__atomic_exchange_n(word, 2u, __ATOMIC_ACQUIRE) != 0u) {
        saw_futex_wait(word, 2u);
    }
}

void __saw_rt_lock_release(void *state) {
    uint32_t *word = (uint32_t *)state;
    if (__atomic_exchange_n(word, 0u, __ATOMIC_RELEASE) == 2u) {
        saw_futex_wake_one(word);
    }
}

/* ---- DF-113a: no C struct layout (design 232) --------------------------
 * `struct epoll_event` is `__attribute__((packed))` ON x86_64 ONLY — the
 * kernel header spells it
 *
 *     #ifdef __x86_64__
 *     #define EPOLL_PACKED __attribute__((packed))
 *     #else
 *     #define EPOLL_PACKED
 *     #endif
 *
 * so the event is 12 bytes with `data` at 4 on x86_64 and 16 bytes with
 * `data` at 8 on every other Linux arch (aarch64 among them). host_linux/
 * reactor.saw had the x86_64 numbers written out as literals, which read the
 * ready token out of the padding on aarch64 and latched a garbage pointer —
 * the same shape of bug as the open(2) flag table above, and blocked by the
 * same gap: Saw cannot see a C struct's ABI layout, so the one language that
 * can reports it. Compiled per target triple, so the answer is the target's.
 *
 * Linux-only: the seam has no macOS caller (kqueue's `struct kevent` is a
 * natural-ABI layout there). */
#include <sys/epoll.h>

long __saw_epoll_event_size(void) {
    return (long)sizeof(struct epoll_event);
}

long __saw_epoll_data_offset(void) {
    return (long)offsetof(struct epoll_event, data);
}
#endif /* __linux__ */
