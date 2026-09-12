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
#include <string.h>
#include <pthread.h>
#include <fcntl.h>
#include <unistd.h>
/* design 272 unit 2: the socket-option and SIGPIPE-suppression macros. */
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>

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

/* ---- design 242 ruling 4: the daemon-thread fate -----------------------
 * `Thread<T>.detach()`. C for the same DF-113b reason as its spawn twin plus
 * one of its own: the block's ownership handshake is an ATOMIC EXCHANGE on a
 * word inside a caller-owned allocation, and Saw has no atomic operation over
 * raw memory (`Atomic<Int>` is a TYPE, and the block is not one).
 *
 * `ctrl` is the thread control block. Two things happen, in this order:
 *
 *   1. `pthread_detach` on the handle in the block's first slot, so the OS
 *      reclaims the thread's own resources when it exits — nobody will join it.
 *   2. The block's ownership passes to the thread's exit path. The word at
 *      `+2 words` holds the block's SIZE while both parties are live; exchange
 *      0 into it, and if what comes back is NEGATIVE the thread already
 *      finished and left `-size` behind, so nobody else will free the block and
 *      this call does. Otherwise the thread is still running and ITS exit sees
 *      the 0 and frees. Exactly one side frees, always, with no lock and no
 *      wait — the size travels in the word precisely so this body can free
 *      without knowing `T`.
 *
 * The layout knowledge here is one word deep and is frozen in rt/ABI.md
 * alongside the seam; spawn codegen writes the other end
 * (`_generate_spawn` / `_generate_spawn_trampoline` in sawc/codegen/calls.py). */
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

/* ---- design 272 unit 2 (SL-229): socket options ------------------------
 * The portable option TAG -> this host's (level, name). Here for the same
 * reason `__saw_open_flags` is here: these are C MACROS whose values differ by
 * host, and C is the one language that can read them. Writing the numbers into
 * the Saw runtime would mean hardcoding 0xffff/0x1022 on one host and 1/9 on
 * the other and hoping every future platform agrees; asking the headers cannot
 * drift. `-1` means this host has no such option, which
 * `__saw_rt_socket_set_option` turns into a refusal rather than a silent no-op.
 *
 * Tags are the table in ABI.md: 1 NoDelay, 2 KeepAlive, 3 ReuseAddress.
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

/* The two halves of ONE contract (design 272 D3-3): a write to a socket whose
 * peer has gone reports EPIPE and never raises SIGPIPE, whose default action
 * would kill the process — so a server cannot be killed by a client that hung
 * up, and the failure arrives as an ordinary Result the handler can answer.
 *
 * macOS has SO_NOSIGPIPE on the socket; Linux has MSG_NOSIGNAL on the send.
 * Both hosts define both functions so rt/common/os_ops.saw calls one name
 * unconditionally, and each is a no-op on the host that uses the other half.
 *
 * PER SOCKET rather than a process-wide SIG_IGN: an ignored disposition is
 * inherited across execve and rt/common/proc.saw does not reset dispositions
 * before execvp, so a process-wide ignore would reach every child a Saw program
 * spawns. Pipes keep their behaviour; only sockets change.
 *
 * The setsockopt return is ignored deliberately: this is hardening the runtime
 * applies to every socket it creates, not something a caller asked for, and a
 * kernel that refused it still hands back a working socket.
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

/* ---- design 272 unit 3 (SL-228): signals as reactor-readable events -----
 *
 * std.signal's SURFACE is a suspending watch with no callbacks anywhere: a
 * watch handle whose `next()` parks the task on the reactor exactly like a
 * socket read. This is the delivery mechanism under it.
 *
 * WHY A SELF-PIPE rather than the kqueue/signalfd natives the issue sketched.
 * The sketch invited this check ("whether any __saw_rt_* seam addition is
 * needed or the reactor side suffices"), and the answer is that the pipe wins
 * on three counts that matter more than using the fancier primitive:
 *
 *   * ZERO ABI CHANGE. A pipe read end is an ordinary readable descriptor, so
 *     it registers through the reactor seam that already exists. EVFILT_SIGNAL
 *     needs a signal-shaped registration the frozen `(fd, write, token)` seam
 *     cannot express, so the native route means new frozen seams on a contract
 *     that is deliberately hard to change.
 *   * ONE IMPLEMENTATION, BOTH HOSTS. kqueue's EVFILT_SIGNAL and Linux's
 *     signalfd are different enough (one observes delivery and needs the
 *     disposition set to SIG_IGN, the other consumes a BLOCKED signal and needs
 *     a mask) that the native route is two mechanisms wearing one seam, tested
 *     twice and divergent in exactly the corners signals are hard in.
 *   * NO THREAD-ORDERING HAZARD, which is the decisive one. signalfd requires
 *     the signal blocked in EVERY thread, and a thread that already existed
 *     when the watch began cannot be made to block it — a process-directed
 *     signal delivered to such a thread takes the DEFAULT action and kills the
 *     process. Masking at `__saw_rt_thread_spawn` covers threads created after
 *     the watch and nothing covers the ones before it. A handler has no such
 *     ordering requirement: it runs on whichever thread takes the signal and
 *     writes the pipe from there.
 *
 * The handler is runtime-internal and invisible from Saw — the ruling that
 * forbids callbacks is about the surface a program writes against, and no
 * program written against this one ever names a handler.
 *
 * ASYNC-SIGNAL-SAFETY: the handler reads three `volatile sig_atomic_t` slots
 * and does one `write(2)` of one byte. `write` is on POSIX's async-signal-safe
 * list and a `sig_atomic_t` load is defined in a handler by definition; nothing
 * else happens in there, and in particular NO LOCK IS TAKEN (see RULE 1 below
 * for why that is mandatory rather than tidy). A full pipe is ignored on
 * purpose — the pipe is an EDGE, not a queue, and one pending byte already
 * means "this signal fired". Non-realtime signals coalesce in the kernel
 * anyway, so a count was never available to promise.
 */
#include <signal.h>
#include <errno.h>

#ifndef NSIG
#define NSIG 65
#endif

/* THE TWO CONCURRENCY RULES, added by SL-228 review r1 which reproduced a
 * failure of each. Both are properties of this block as a whole, so they are
 * stated here rather than at one function.
 *
 * RULE 1 — THE WATCH TRANSACTION IS SERIALIZED. Initialization, the
 * already-watched check, descriptor publication and `sigaction` installation
 * are ONE transaction under `__saw_sig_m`. Unsynchronized, two threads could
 * both pass the availability check and both return a successful watch for one
 * signal: the single-owner contract broken, one pipe unreachable, and — worst —
 * a saved "previous" disposition that is Saw's OWN handler, so dropping either
 * handle restores the wrong thing. `volatile sig_atomic_t` makes individual
 * loads and stores well defined; it does not make a transaction atomic, which
 * is the confusion the first version rested on.
 *
 * The HANDLER never takes this lock and must never take any lock: it can
 * interrupt a thread that is already inside `__saw_sig_m` (a thread calling
 * `watch` can itself be signalled), and a handler blocking on a mutex its own
 * thread holds is an immediate deadlock. `sigaction` and `pthread_mutex_*` on
 * the watch/unwatch side are ordinary calls on ordinary threads, so serializing
 * them is free of async-signal-safety concerns.
 *
 * RULE 2 — NOTHING A HANDLER CAN REACH IS EVER RECLAIMED. The pipe for a signal
 * is created at its FIRST watch and lives for the whole process; `unwatch`
 * restores the disposition and drains, and closes NOTHING. This is what makes
 * the handler-versus-teardown race unlosable rather than merely unlikely.
 *
 * Restoring a disposition stops FUTURE handler entries. It says nothing about a
 * handler already running on another thread that has ALREADY loaded the write
 * descriptor and not yet written. Close the pipe under it and the descriptor
 * number is free for reuse; the delayed handler then writes its byte into
 * whatever unrelated pipe, socket or file inherits that number. A mutex around
 * watch/unwatch cannot fix this — the handler is not inside the mutex and
 * cannot be made to be.
 *
 * So the descriptor the handler loads is a value that, once published, is valid
 * FOREVER. There is no window because there is no reclamation. The cost is
 * bounded and small: two descriptors per signal ever watched, at most seven
 * signals in the ruled `Signal` set, so fourteen descriptors for a process that
 * watches every one of them — and zero for a process that watches none.
 *
 * RULE 3 — THE HANDLER TAKES EXACTLY ONE SNAPSHOT, AND THE TAG NEVER RECURS.
 * This is the accuracy half, and revision 3 of this file got it wrong twice in
 * ways the r3 review reproduced. Both failures are recorded because the shape
 * of the fix only makes sense against them.
 *
 * Not-reclaiming (RULE 2) makes a late write SAFE; it does not make it
 * ACCURATE. A byte from a previous watch sits in a pipe the NEXT watch is
 * reading, and mistaking it for a fresh delivery returns from `next()` in a
 * shutdown path and cancels a server nobody signalled. So a delivery carries a
 * TAG naming the watch it belongs to, and the drain keeps only current ones.
 *
 *   * r3 FAILURE ONE — A TORN SNAPSHOT. The handler read `watched`, the
 *     descriptor and the generation as three separate loads. Pause it after it
 *     observes `watched == 1`, unwatch and rewatch once on another thread,
 *     resume: it then reads the NEW generation and labels its OLD delivery
 *     current. Measured `stale deliveries accepted=1` after ONE rewatch.
 *     Widening the tag does not touch this.
 *   * r3 FAILURE TWO — A RECURRING TAG. The tag was seven bits, so 128
 *     unwatch/rewatch cycles while a handler sits paused before its write bring
 *     it back to equal and the stale byte is accepted. Ordering the snapshot
 *     correctly does not touch this.
 *
 * So the protocol is ONE WORD, loaded ONCE. `__saw_sig_state[signo]` packs the
 * generation in its high 63 bits and the watched flag in bit 0, and the handler
 * derives BOTH from a single atomic acquire load. There is no interleaving that
 * can give it a `watched` from one watch and a generation from another, because
 * there is only one read. That is failure one closed by construction rather
 * than by ordering discipline somebody has to maintain.
 *
 * The generation is 63 bits, MONOTONIC, and never reset — `unwatch` clears bit
 * 0 and leaves the counter alone. Recurrence therefore needs 2^63 ≈ 9.2e18
 * watch/unwatch cycles to complete while one handler stays paused between its
 * snapshot and its write. At one cycle per nanosecond, which no real program
 * approaches, that is over 290 years of uninterrupted rewatching. That is the
 * bound, stated rather than waved at: the tag cannot recur in any execution
 * this process can have.
 *
 * The handler writes the FULL 63-bit tag, not a byte of it. POSIX guarantees a
 * write of at most PIPE_BUF (512 bytes minimum; 4096 on both hosted targets) to
 * a pipe is atomic, so an eight-byte record never interleaves with another
 * handler's and the pipe holds a whole number of records. The drain reads into
 * a buffer that is a multiple of the record size, so it never splits one.
 *
 * WHICH SIDE VALIDATES is the last piece and is not interchangeable: the
 * handler STAMPS and the reader VALIDATES. A handler that checked whether its
 * tag was still current and then wrote would have a window between the check
 * and the write — the same time-of-check-to-time-of-use shape in a smaller
 * font. The reader reads bytes that already exist and judges them against a
 * word it loads itself; there is nothing for it to race.
 *
 * The write DESCRIPTOR is read separately and that is sound, which is worth
 * stating because it looks like a second load: it is written exactly once per
 * signal, under the mutex, BEFORE the first handler for that signal can exist,
 * and is never changed or closed thereafter (RULE 2). A load of a value that is
 * immutable for the process's life cannot disagree with anything. The
 * release/acquire pair orders that publication ahead of any `watched` a handler
 * can observe, so a handler never sees a watch whose descriptor is not there.
 */
static pthread_mutex_t __saw_sig_m = PTHREAD_MUTEX_INITIALIZER;

/* THE one word per signal (RULE 3): generation in bits 63..1, watched in bit 0.
 * Written only under `__saw_sig_m`, with release; read by the handler and the
 * drain with acquire. A `sig_atomic_t` would not do — it is only guaranteed
 * wide enough for a small integer, and this has to carry a 63-bit counter. */
typedef unsigned long long saw_sig_word;
static saw_sig_word __saw_sig_state[NSIG];

/* The handler loads this word with a plain atomic load, so it must be lock-free
 * or the handler could take a lock (see RULE 1 on why that is fatal). Checked at
 * compile time rather than assumed. */
_Static_assert(sizeof(saw_sig_word) == 8,
               "the signal state word carries a 63-bit generation plus a flag");
_Static_assert(__atomic_always_lock_free(sizeof(saw_sig_word), 0),
               "the signal state word must be lock-free: a signal handler loads it");

#define SAW_SIG_WATCHED 1ULL
#define SAW_SIG_GEN(w)  ((w) >> 1)
#define SAW_SIG_WORD(gen, watched) (((saw_sig_word)(gen) << 1) | (watched))

/* The write descriptor. Published ONCE per signal under the mutex, before any
 * handler for it can exist, and never changed or closed (RULE 2) — so the
 * handler's separate load of it cannot disagree with its state snapshot. */
static volatile sig_atomic_t __saw_sig_wr[NSIG];
/* Touched only under `__saw_sig_m`. */
static int __saw_sig_rd[NSIG];
static struct sigaction __saw_sig_old[NSIG];
static int __saw_sig_init = 0;

/* A no-op in the shipped runtime. `tools/signal_hook_shim.py` rewrites the
 * marker below into a call to a test hook, so the race pins can pause a REAL
 * handler at the one point that matters. The marker is an inert comment here;
 * the generator fails loudly if it ever stops matching, so the pins can never
 * drift onto a stale copy of this logic. */

static void __saw_sig_handler(int signo) {
    /* errno is saved and restored: the handler interrupts arbitrary code that
     * may be between a failing syscall and its errno read, and clobbering it
     * there would be a bug with no visible cause. */
    int saved = errno;
    if (signo > 0 && signo < NSIG) {
        /* THE ONE LOAD (RULE 3). Everything this delivery needs to know about
         * the watch it belongs to comes from this single snapshot: whether the
         * signal is watched at all, and which generation to stamp. Splitting it
         * is what let an old handler label its delivery with a new watch's
         * generation. */
        saw_sig_word snap = __atomic_load_n(&__saw_sig_state[signo], __ATOMIC_ACQUIRE);
        if (snap & SAW_SIG_WATCHED) {
            int fd = (int)__saw_sig_wr[signo];
            if (fd >= 0) {
                saw_sig_word tag = SAW_SIG_GEN(snap);
                /* SAW_SIGNAL_TEST_HOOK */
                /* One atomic record: at eight bytes it is far under PIPE_BUF,
                 * so it never interleaves with another handler's. */
                (void)!write(fd, &tag, sizeof(tag));
            }
        }
    }
    errno = saved;
}

/* Discard everything currently in signal `s`'s pipe. Caller holds the lock.
 * Bounded rather than looping to EAGAIN: a pipe holds at most its buffer, and a
 * handler writing concurrently is precisely the case the generation tag — not
 * this drain — is responsible for. */
static void __saw_sig_discard(int s) {
    int fd = __saw_sig_rd[s];
    if (fd < 0) return;
    char buf[256];
    for (int i = 0; i < 512; i++) {
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n <= 0) break;
    }
}

/* The PORTABLE signal tag -> this host's number. The numbers are the whole
 * reason the tag space exists: SIGUSR1 is 30 on macOS and 10 on Linux. Tags are
 * the table in ABI.md and the `Signal` enum in std/signal.saw. */
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

/* Begin watching `signo`: create the pipe, install the handler, and hand back
 * the READ end for the caller to register with the reactor. Returns the fd, or
 * a negative error: -1 for an out-of-range signal, -2 for a second live watch
 * of the same signal (the ruled double-watch policy — the disposition is
 * process-global state and a global with two owners is what the refusal
 * prevents), -3 if the pipe or the handler could not be installed.
 *
 * Both pipe ends are non-blocking: the handler must never block a signalled
 * thread, and the drain side must get EAGAIN rather than hang when it loses a
 * race to another drain. */
long __saw_signal_watch(long signo) {
    int s = (int)signo;
    if (s <= 0 || s >= NSIG) return -1;

    pthread_mutex_lock(&__saw_sig_m);       /* RULE 1: one transaction */

    if (!__saw_sig_init) {
        for (int i = 0; i < NSIG; i++) {
            __saw_sig_wr[i] = -1;
            __saw_sig_rd[i] = -1;
            __saw_sig_state[i] = 0;
        }
        __saw_sig_init = 1;
    }

    /* The single-owner check and everything that follows from it happen under
     * one lock, so two callers cannot both pass it. */
    saw_sig_word cur = __saw_sig_state[s];
    if (cur & SAW_SIG_WATCHED) {
        pthread_mutex_unlock(&__saw_sig_m);
        return -2;
    }

    if (__saw_sig_wr[s] < 0) {
        /* First watch of this signal in this process: create the pipe it will
         * use for the rest of the process's life. Both ends non-blocking — the
         * handler must never block a signalled thread, and a drain that loses a
         * race must get EAGAIN rather than hang. */
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
        /* Re-watch: the pipe is the one the previous watch used. Clear whatever
         * it holds so this watch starts empty. Bytes a still-in-flight handler
         * writes AFTER this point carry the OLD generation and the drain
         * discards them — that is the tag's job, not this discard's. */
        __saw_sig_discard(s);
    }

    /* PUBLISH BEFORE INSTALLING. The generation advances and the watched bit is
     * set in one release store, and only then is the handler installed — so the
     * instant a handler can run it already sees this watch's generation. The
     * reverse order would drop a delivery that arrived between `sigaction` and
     * the publish, which is a lost wakeup rather than a stale one.
     *
     * MONOTONIC: the counter only ever advances, here, for the process's life.
     * `unwatch` clears the flag and leaves it alone. That is what makes the
     * 2^63 recurrence bound a bound and not a wrap. */
    saw_sig_word gen = SAW_SIG_GEN(__saw_sig_state[s]) + 1;
    __atomic_store_n(&__saw_sig_state[s], SAW_SIG_WORD(gen, SAW_SIG_WATCHED),
                     __ATOMIC_RELEASE);

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = __saw_sig_handler;
    sigemptyset(&sa.sa_mask);
    /* SA_RESTART so watching a signal does not start returning EINTR from every
     * blocking call elsewhere in the program — the watch is meant to be
     * invisible to code that is not watching. */
    sa.sa_flags = SA_RESTART;
    if (sigaction(s, &sa, &__saw_sig_old[s]) != 0) {
        /* Roll the flag back, KEEPING the advanced generation: a generation is
         * spent once it has been published, whether or not the watch took. The
         * pipe stays allocated for a later watch; it was not the failure. */
        __atomic_store_n(&__saw_sig_state[s], SAW_SIG_WORD(gen, 0),
                         __ATOMIC_RELEASE);
        pthread_mutex_unlock(&__saw_sig_m);
        return -3;
    }

    int rd = __saw_sig_rd[s];
    pthread_mutex_unlock(&__saw_sig_m);
    return (long)rd;
}

/* Stop watching `signo`: restore the disposition the watch replaced and leave
 * the pipe empty for whoever watches next. Idempotent.
 *
 * CLOSES NOTHING — see RULE 2 above. A handler already past its descriptor load
 * on another thread will write one byte into a pipe this process still owns;
 * that byte carries the OLD generation and the next watch's drain discards it.
 * Closing here is what let a delayed handler write into an unrelated resource
 * that inherited the descriptor number. */
void __saw_signal_unwatch(long signo) {
    int s = (int)signo;
    if (s <= 0 || s >= NSIG) return;

    pthread_mutex_lock(&__saw_sig_m);
    saw_sig_word cur = __saw_sig_state[s];
    if (!(cur & SAW_SIG_WATCHED)) {
        pthread_mutex_unlock(&__saw_sig_m);
        return;
    }
    /* Restore FIRST: it is what stops further handler entries. Then clear the
     * watched bit, KEEPING the generation — the counter is monotonic for the
     * process's life, and a handler that snapshotted this watch still carries
     * its generation and will be judged against a later one. */
    (void)sigaction(s, &__saw_sig_old[s], NULL);
    __atomic_store_n(&__saw_sig_state[s], SAW_SIG_WORD(SAW_SIG_GEN(cur), 0),
                     __ATOMIC_RELEASE);
    __saw_sig_discard(s);
    pthread_mutex_unlock(&__saw_sig_m);
}

/* Send `signo` to THIS process (`raise`). Returns 0 or -1. The deterministic
 * way a test exercises a watch, and the way a program triggers its own shutdown
 * path. */
long __saw_signal_raise(long signo) {
    return raise((int)signo) == 0 ? 0 : -1;
}

/* Take whatever the handler has written off signal `signo`'s pipe, KEEPING ONLY
 * the bytes that belong to the current watch. Returns the count of matching
 * bytes (> 0 = at least one delivery this watch should report), or -1 for
 * "nothing pending" — which includes having read only stale bytes, so the
 * caller re-parks instead of reporting a delivery that was not one.
 *
 * Takes the SIGNAL rather than a descriptor: validating the generation means
 * knowing which watch is current, and the signal is the key to that. The
 * caller's descriptor is still the one it parks on.
 *
 * THIS IS THE VALIDATING SIDE of the generation protocol (see RULE 2). A byte
 * stamped by a handler that was in flight across a teardown carries the
 * previous generation and is discarded here. The handler never validates,
 * because a handler that checked and then wrote would have a window between
 * the two; a reader that reads and then judges has none.
 *
 * It is in C rather than Saw for the reason std.net keeps its reads behind
 * `__saw_rt_tcp_read`: a Saw `extern "C" func read(...)` declaration is
 * program-GLOBAL, so std declaring one collides with any program that declares
 * `read` itself — the suite's offload tests declare it `blocking`. Keeping the
 * syscall here means std.signal declares no libc symbol at all.
 *
 * The count is not a delivery count and is never reported as one: non-realtime
 * signals coalesce in the kernel, so the number of bytes was never something
 * the API could promise. The caller uses only "> 0". */
long __saw_signal_drain(long signo) {
    int s = (int)signo;
    if (s <= 0 || s >= NSIG) return -1;
    int fd = __saw_sig_rd[s];
    if (fd < 0) return -1;
    /* The reader loads the word itself and judges what it finds against it.
     * Nothing here races: the bytes already exist, and a handler that writes
     * during this loop either carries the current tag (a real delivery, counted
     * now or on the next call) or an older one (discarded). */
    saw_sig_word want = SAW_SIG_GEN(
        __atomic_load_n(&__saw_sig_state[s], __ATOMIC_ACQUIRE));
    long matched = 0;
    /* A whole number of records, so a read can never split one: every write is
     * one atomic eight-byte record and this asks for a multiple of eight. */
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
