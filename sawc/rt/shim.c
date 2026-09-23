/* The Saw runtime C shim (design 113b).
 *
 * The `__saw_rt_*` runtime ABI (sawc/rt/ABI.md) is authored in Saw under
 * `--runtime-build`, except the bodies below. Each is here because of a
 * specific Saw FFI gap, named by its DF number; a body moves to Saw when its
 * gap closes. Keep this file as small as the gaps require.
 *
 * This is the hosted (macOS/Linux) shim, compiled with clang by
 * sawc/rt_build.py.
 *
 * `_GNU_SOURCE` must precede the first include: glibc returns EAI_NODATA but
 * only declares it under `__USE_GNU`, and without the macro that code falls
 * through `__saw_gai_tag` to `Other` instead of `NotFound`.
 */
#define _GNU_SOURCE

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>

/* ---- DF-113a: no extern C global ---------------------------------------
 * Saw cannot name `stdout`. Output goes through stdio rather than raw
 * `write(2)` so it stays on one buffered stream with the printf-based Float
 * path, which is what keeps `print` output in program order (rt/ABI.md).
 */
void __saw_rt_write(const char *ptr, size_t len) {
    fwrite(ptr, 1, len, stdout);
    fflush(stdout);
}

/* The panic sink: write the message, then abort. */
__attribute__((noreturn))
void __saw_rt_panic(const char *msg, size_t len) {
    __saw_rt_write(msg, len);
    abort();
}

/* ---- DF-113a: no C macro -----------------------------------------------
 * `open(2)` flag bits differ per host, so `__saw_rt_fs_open` takes a portable
 * mode and this translates it. Keep the mode numbers in step with `OpenMode`
 * in sawc/std/file.saw. */
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
 * The getaddrinfo walk is Saw (sawc/rt/common/os_ops.saw); these projections
 * are header facts it cannot see. `struct addrinfo` orders `ai_addr` and
 * `ai_canonname` differently on glibc and macOS, and the `EAI_*` codes differ
 * in value and sign between hosts.
 */
#include <netdb.h>
#include <netinet/in.h>
#include <sys/socket.h>

/* The next entry in the list, or NULL at its end. */
const void *__saw_ai_next(const void *entry) {
    return (const void *)((const struct addrinfo *)entry)->ai_next;
}

/* Writes the entry's IPv4 address (network byte order) to `out` and returns 1
 * if it is AF_INET, else returns 0. A status rather than a sentinel, because
 * 0.0.0.0 is a valid address. */
long __saw_ai_ipv4(const void *entry, unsigned int *out) {
    const struct addrinfo *ai = (const struct addrinfo *)entry;
    if (ai->ai_family != AF_INET || ai->ai_addr == NULL) return 0;
    *out = ((const struct sockaddr_in *)(const void *)ai->ai_addr)->sin_addr.s_addr;
    return 1;
}

/* A getaddrinfo(3) failure code as a portable SysError tag (rt/ABI.md), or 0
 * for EAI_SYSTEM, whose cause the caller reads from errno via
 * `__saw_rt_last_syserror()`. */
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

/* ---- DF-113a: no extern C global ---------------------------------------
 * `__saw_rt_proc_spawn_env` sets the child's environment by pointing
 * `environ` at the merged array between fork and exec, which keeps
 * `execvp`'s PATH search. Get and set are a pointer load and store, so the
 * set is async-signal-safe in that window; the merge itself runs in the
 * parent (rt/common/proc.saw). macOS spells the variable `_NSGetEnviron()`. */
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
 * `entry` is a raw `void *(*)(void *)` start routine, which Saw cannot
 * forward. Returns the `pthread_t` as a word; spawn codegen stores it in the
 * control block and `__saw_rt_thread_join` takes it back (design 117). */
long __saw_rt_thread_spawn(void *(*entry)(void *), void *env) {
    pthread_t t;
    pthread_create(&t, NULL, entry, env);
    return (long)t;
}

/* ---- DF-113b, plus no atomics over raw memory (design 242) --------------
 * `Thread<T>.detach()`. Detaches the OS thread, then hands ownership of the
 * control block to whichever side finishes last. The word at `+2 words` holds
 * the block's size while both sides are live; exchanging 0 into it returns a
 * negative `-size` if the thread already exited, and then this call frees the
 * block. Otherwise the thread's exit sees the 0 and frees it. Exactly one side
 * frees, with no lock. The layout is frozen in rt/ABI.md; the other end is
 * `_generate_spawn_trampoline` in sawc/codegen/calls.py. */
void __saw_rt_dealloc(void *ptr, size_t size, size_t align);

void __saw_rt_thread_detach(void *ctrl) {
    unsigned char *cb = (unsigned char *)ctrl;
    pthread_t t;
    memcpy(&t, cb, sizeof(pthread_t));
    pthread_detach(t);
    long *state = (long *)(void *)(cb + 2 * sizeof(void *));
    long prev = __atomic_exchange_n(state, (long)0, __ATOMIC_ACQ_REL);
    if (prev < 0) {
        __saw_rt_dealloc(ctrl, (size_t)(-prev), 16);
    }
}

/* ---- DF-113c: no variadic extern ---------------------------------------
 * `fcntl` is variadic, and a fixed-arity declaration of a variadic function
 * is wrong on some ABIs: on Apple arm64 the F_SETFL argument would go in a
 * register the callee reads from the stack. So it is called from C. Returns
 * 0, or -1 if F_GETFL fails. */
long __saw_rt_set_nonblocking(long fd) {
    int flags = fcntl((int)fd, F_GETFL, 0);
    if (flags < 0) return -1;
    fcntl((int)fd, F_SETFL, flags | O_NONBLOCK);
    return 0;
}

/* ---- DF-113a: no C macro (design 272) ----------------------------------
 * A portable socket-option tag to this host's (level, name). Tags are the
 * table in rt/ABI.md: 1 NoDelay, 2 KeepAlive, 3 ReuseAddress. -1 means the
 * host has no such option, which `__saw_rt_socket_set_option` refuses rather
 * than ignoring.
 */
long __saw_sockopt_level(long option) {
    switch (option) {
        case 1: return IPPROTO_TCP;
        case 2: return SOL_SOCKET;
        case 3: return SOL_SOCKET;
        default: return -1;
    }
}

long __saw_sockopt_name(long option) {
    switch (option) {
        case 1: return TCP_NODELAY;
        case 2: return SO_KEEPALIVE;
        case 3: return SO_REUSEADDR;
        default: return -1;
    }
}

/* A write to a socket whose peer has gone should report EPIPE rather than
 * raise SIGPIPE. Linux gets this per send (MSG_NOSIGNAL); macOS sends with
 * flags 0 after an attempted per-socket SO_NOSIGPIPE setup. Both functions
 * exist on both hosts so rt/common/os_ops.saw calls them unconditionally.
 *
 * Per socket, not a process-wide SIG_IGN: an ignored disposition is inherited
 * across execve and would reach every child the program spawns.
 *
 * The setsockopt result is ignored: this is best-effort hardening applied to
 * every socket the runtime creates. If a kernel refused it, that socket would
 * still work but could raise SIGPIPE on a dead peer.
 */
void __saw_socket_suppress_sigpipe(long fd) {
#ifdef SO_NOSIGPIPE
    int one = 1;
    (void)setsockopt((int)fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one));
#else
    (void)fd;
#endif
}

long __saw_socket_send_flags(void) {
#ifdef MSG_NOSIGNAL
    return MSG_NOSIGNAL;
#else
    return 0;
#endif
}

/* ---- Signals as reactor-readable events (design 272) --------------------
 *
 * std.signal's `next()` parks on the reactor like a socket read. Delivery is
 * a self-pipe: the handler writes a record to a pipe whose read end is an
 * ordinary reactor fd. This needs no new ABI seam, is one mechanism on both
 * hosts, and, unlike signalfd, does not require the signal to be blocked in
 * every thread, including threads that existed before the watch began.
 *
 * The handler is async-signal-safe: one atomic load, one `write(2)`, no locks.
 * A write to a full pipe is dropped. Normally that loses nothing: one pending
 * current record already means "fired", and non-realtime signals coalesce
 * anyway. Every (re-)watch drains the pipe (bounded, but past the default
 * pipe capacity); after that, the only stale writers are handlers that took
 * their snapshot before the watch began, at most one record per thread (a
 * handler blocks its own signal while it runs). Nothing enforces that the
 * thread count stays below the pipe's record capacity. If enough threads
 * were paused in that window to fill the pipe with stale records, a current
 * record could be dropped and the drain would report nothing. That case is
 * not handled.
 *
 * Three rules hold for the block as a whole. Design 272 records the races
 * each one closes.
 *
 * RULE 1: watch and unwatch are serialized under `__saw_sig_m`. The handler
 * never takes a lock; it can interrupt a thread that holds this one.
 *
 * RULE 2: nothing a handler can reach is ever reclaimed. A signal's pipe is
 * created at its first watch and lives for the process; `unwatch` closes
 * nothing. A handler that already loaded the write fd therefore can never
 * write into an unrelated file that reused the fd number. The cost is at most
 * two fds per watchable signal.
 *
 * RULE 3: each delivery is tagged with the watch it belongs to, taken from
 * ONE atomic load. `__saw_sig_state[signo]` packs a 63-bit monotonic
 * generation (bits 63..1) with the watched flag (bit 0), so the handler cannot
 * pair one watch's flag with another's generation, and the tag cannot recur
 * in practice. The handler stamps the full 8-byte tag (an atomic pipe write,
 * far under PIPE_BUF); the drain validates it against the current generation.
 * Validation must happen on the reader side: a handler that checked and then
 * wrote would have a window between the two.
 *
 * The write fd is read separately from the state word. That is sound because
 * it is published once, under the mutex, before any handler for that signal
 * can run, and never changes (RULE 2).
 */
#include <signal.h>
#include <errno.h>

#ifndef NSIG
#define NSIG 65
#endif

static pthread_mutex_t __saw_sig_m = PTHREAD_MUTEX_INITIALIZER;

/* Generation in bits 63..1, watched in bit 0 (RULE 3). Written only under
 * `__saw_sig_m` with release; read with acquire. `sig_atomic_t` is not wide
 * enough for the counter. */
typedef unsigned long long saw_sig_word;
static saw_sig_word __saw_sig_state[NSIG];

/* The handler's load must be lock-free (RULE 1). */
_Static_assert(sizeof(saw_sig_word) == 8,
               "the signal state word carries a 63-bit generation plus a flag");
_Static_assert(__atomic_always_lock_free(sizeof(saw_sig_word), 0),
               "the signal state word must be lock-free: a signal handler loads it");

#define SAW_SIG_WATCHED 1ULL
#define SAW_SIG_GEN(w)  ((w) >> 1)
#define SAW_SIG_WORD(gen, watched) (((saw_sig_word)(gen) << 1) | (watched))

/* Published once per signal and never changed or closed (RULE 2). */
static volatile sig_atomic_t __saw_sig_wr[NSIG];
/* Touched only under `__saw_sig_m`. */
static int __saw_sig_rd[NSIG];
static struct sigaction __saw_sig_old[NSIG];
static int __saw_sig_init = 0;

/* tools/signal_hook_shim.py rewrites the SAW_SIGNAL_TEST_HOOK marker in the
 * handler into a test hook, so the race pins can pause a real handler there.
 * It fails loudly if the marker stops matching. */

static void __saw_sig_handler(int signo) {
    /* Preserve errno for the code this handler interrupted. */
    int saved = errno;
    if (signo > 0 && signo < NSIG) {
        /* The one load (RULE 3): the watched flag and the tag come from the
         * same snapshot. */
        saw_sig_word snap = __atomic_load_n(&__saw_sig_state[signo], __ATOMIC_ACQUIRE);
        if (snap & SAW_SIG_WATCHED) {
            int fd = (int)__saw_sig_wr[signo];
            if (fd >= 0) {
                saw_sig_word tag = SAW_SIG_GEN(snap);
                /* SAW_SIGNAL_TEST_HOOK */
                (void)!write(fd, &tag, sizeof(tag));
            }
        }
    }
    errno = saved;
}

/* Discard what is currently in signal `s`'s pipe. Caller holds the lock.
 * Bounded rather than looping to EAGAIN; a concurrent handler's stale write
 * is the generation tag's job, not this drain's. */
static void __saw_sig_discard(int s) {
    int fd = __saw_sig_rd[s];
    if (fd < 0) return;
    char buf[256];
    for (int i = 0; i < 512; i++) {
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n <= 0) break;
    }
}

/* A portable signal tag to this host's number (SIGUSR1 is 30 on macOS, 10 on
 * Linux). Tags match rt/ABI.md and the `Signal` enum in std/signal.saw. */
long __saw_signal_number(long tag) {
    switch (tag) {
        case 1: return SIGTERM;
        case 2: return SIGINT;
        case 3: return SIGHUP;
        case 4: return SIGQUIT;
        case 5: return SIGUSR1;
        case 6: return SIGUSR2;
#ifdef SIGWINCH
        case 7: return SIGWINCH;
#endif
        default: return -1;
    }
}

/* Begin watching `signo` and return the pipe's read end for the reactor.
 * Errors: -1 signal out of range, -2 already watched (one owner per
 * process-global disposition), -3 pipe or handler setup failed. */
long __saw_signal_watch(long signo) {
    int s = (int)signo;
    if (s <= 0 || s >= NSIG) return -1;

    pthread_mutex_lock(&__saw_sig_m);       /* RULE 1 */

    if (!__saw_sig_init) {
        for (int i = 0; i < NSIG; i++) {
            __saw_sig_wr[i] = -1;
            __saw_sig_rd[i] = -1;
            __saw_sig_state[i] = 0;
        }
        __saw_sig_init = 1;
    }

    saw_sig_word cur = __saw_sig_state[s];
    if (cur & SAW_SIG_WATCHED) {
        pthread_mutex_unlock(&__saw_sig_m);
        return -2;
    }

    if (__saw_sig_wr[s] < 0) {
        /* First watch: create the process-lifetime pipe. Both ends are
         * non-blocking, so the handler never blocks a signalled thread and a
         * drain that loses a race gets EAGAIN instead of hanging. */
        int fds[2];
        if (pipe(fds) != 0) {
            pthread_mutex_unlock(&__saw_sig_m);
            return -3;
        }
        if (fcntl(fds[0], F_SETFL, fcntl(fds[0], F_GETFL, 0) | O_NONBLOCK) < 0 ||
            fcntl(fds[1], F_SETFL, fcntl(fds[1], F_GETFL, 0) | O_NONBLOCK) < 0) {
            close(fds[0]); close(fds[1]);
            pthread_mutex_unlock(&__saw_sig_m);
            return -3;
        }
        __saw_sig_rd[s] = fds[0];
        __saw_sig_wr[s] = fds[1];       /* published once, valid forever */
    } else {
        /* Re-watch reuses the pipe; start it empty. Late writes from an old
         * handler carry an old generation and the drain drops them. */
        __saw_sig_discard(s);
    }

    /* Publish the new generation before installing the handler, so a handler
     * that runs immediately already sees this watch. The other order would
     * lose a delivery. The generation only ever advances. */
    saw_sig_word gen = SAW_SIG_GEN(__saw_sig_state[s]) + 1;
    __atomic_store_n(&__saw_sig_state[s], SAW_SIG_WORD(gen, SAW_SIG_WATCHED),
                     __ATOMIC_RELEASE);

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = __saw_sig_handler;
    sigemptyset(&sa.sa_mask);
    /* SA_RESTART: watching a signal must not make unrelated blocking calls
     * start returning EINTR. */
    sa.sa_flags = SA_RESTART;
    if (sigaction(s, &sa, &__saw_sig_old[s]) != 0) {
        /* Clear the flag but keep the generation: once published it is spent.
         * The pipe stays for a later watch. */
        __atomic_store_n(&__saw_sig_state[s], SAW_SIG_WORD(gen, 0),
                         __ATOMIC_RELEASE);
        pthread_mutex_unlock(&__saw_sig_m);
        return -3;
    }

    int rd = __saw_sig_rd[s];
    pthread_mutex_unlock(&__saw_sig_m);
    return (long)rd;
}

/* Stop watching `signo`: restore the previous disposition and empty the pipe.
 * Idempotent. Closes nothing (RULE 2). */
void __saw_signal_unwatch(long signo) {
    int s = (int)signo;
    if (s <= 0 || s >= NSIG) return;

    pthread_mutex_lock(&__saw_sig_m);
    saw_sig_word cur = __saw_sig_state[s];
    if (!(cur & SAW_SIG_WATCHED)) {
        pthread_mutex_unlock(&__saw_sig_m);
        return;
    }
    /* Restore first, which stops new handler entries; then clear the flag and
     * keep the generation. */
    (void)sigaction(s, &__saw_sig_old[s], NULL);
    __atomic_store_n(&__saw_sig_state[s], SAW_SIG_WORD(SAW_SIG_GEN(cur), 0),
                     __ATOMIC_RELEASE);
    __saw_sig_discard(s);
    pthread_mutex_unlock(&__saw_sig_m);
}

/* Send `signo` to this process. Returns 0 or -1. */
long __saw_signal_raise(long signo) {
    return raise((int)signo) == 0 ? 0 : -1;
}

/* Drain signal `signo`'s pipe, counting only records tagged with the current
 * generation (RULE 3). Returns that count (> 0 means a delivery), or -1 if
 * nothing current was pending, so the caller re-parks. The count is not a
 * delivery count; callers use only "> 0".
 *
 * In C rather than Saw because a Saw `extern "C" func read` is program-global
 * and would collide with programs that declare `read` themselves. */
long __saw_signal_drain(long signo) {
    int s = (int)signo;
    if (s <= 0 || s >= NSIG) return -1;
    int fd = __saw_sig_rd[s];
    if (fd < 0) return -1;
    saw_sig_word want = SAW_SIG_GEN(
        __atomic_load_n(&__saw_sig_state[s], __ATOMIC_ACQUIRE));
    long matched = 0;
    /* A multiple of the record size, so a read never splits a record. */
    saw_sig_word buf[16];
    for (;;) {
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n <= 0) break;
        size_t records = (size_t)n / sizeof(saw_sig_word);
        for (size_t i = 0; i < records; i++) {
            if (buf[i] == want) matched++;
        }
        if ((size_t)n < sizeof(buf)) break;   /* drained what was there */
    }
    return matched > 0 ? matched : -1;
}

/* ---- DF-113b: the blocking-extern offload thread ------------------------
 * The offload seams are Saw (sawc/rt/common/offload.saw); this thread body is
 * C because it calls a raw function pointer. `job->fn` is a compiler-
 * synthesized thunk that reads its arguments from `job->args` (design 183),
 * so this file needs no arity knowledge. The body touches only its own job
 * and the pipe's write end: run, store the result, publish `done` with
 * release, then write one byte.
 *
 * Layout must match `struct Job` in offload.saw (48 bytes, static_assert
 * there). `done` is accessed atomically on both sides. */
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

/* The offload thread's address, for `offload_start` to pass to
 * `__saw_rt_thread_spawn`. */
void *__saw_offload_thread_ptr(void) {
    return (void *)__saw_offload_thread;
}

/* ---- DF-186c: no 32-bit atomics through a pointer, no variadic extern ----
 * The Linux body of `__saw_rt_lock_acquire` / `_release`, the one-word lock
 * behind `Mutex<T>` (rt/ABI.md). The macOS body is Saw
 * (sawc/rt/host_macos/lock.saw).
 *
 * The futex word is the low four bytes of the `Int` std passes in; both
 * hosted targets are little-endian. Drepper's three states: 0 unlocked,
 * 1 locked, 2 locked with waiters, so uncontended acquire and release never
 * enter the kernel. Zero is unlocked, so a zero-initialized static `Mutex` is
 * valid.
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
    /* Mark the lock contended before sleeping so the holder knows to wake us.
     * Swapping (not storing) catches a release that happened in between. */
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

/* ---- DF-113a: no C struct layout ---------------------------------------
 * `struct epoll_event` is packed on x86_64 only: 12 bytes with `data` at 4
 * there, 16 bytes with `data` at 8 elsewhere (aarch64 included).
 * host_linux/reactor.saw asks for the target's layout instead of hardcoding
 * it. */
#include <sys/epoll.h>

long __saw_epoll_event_size(void) {
    return (long)sizeof(struct epoll_event);
}

long __saw_epoll_data_offset(void) {
    return (long)offsetof(struct epoll_event, data);
}
#endif /* __linux__ */
