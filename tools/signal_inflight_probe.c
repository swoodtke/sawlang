/* Design 272 unit 3 — the IN-FLIGHT handler pins (SL-228 review r3).
 *
 * These two cells PAUSE A REAL SIGNAL HANDLER between its state snapshot and
 * its write, mutate the watch lifecycle underneath it, and then let it write.
 * That is the interleaving the r3 review used to break revision 3's generation
 * protocol twice, and neither cell can be written from Saw or from C that links
 * the shim as-is — the pause has to happen INSIDE the handler.
 *
 * So this links a GENERATED copy of the shim: `tools/signal_hook_shim.py`
 * substitutes one marker in `sawc/rt/shim.c` for a call to the hook below and
 * changes nothing else. The generator refuses to emit anything if the marker
 * has moved, so a pin can never end up testing a stale transcription.
 *
 * WHAT REVISION 3 DID, and what each cell therefore asserts:
 *
 *   cell A (one rewatch) — r3's handler read `watched`, the descriptor and the
 *   generation as three separate loads. Paused after observing `watched == 1`,
 *   it read the generation AFTER a rewatch and labelled its old delivery
 *   current: `stale deliveries accepted=1` after a SINGLE rewatch. The fix
 *   takes one snapshot, so the tag it writes is the one it saw.
 *
 *   cell B (tag recurrence) — r3's tag was seven bits. Paused before its write,
 *   128 unwatch/rewatch cycles brought the tag back to equal and the stale byte
 *   was accepted. This cell runs 256, and the NUMBER MATTERS: it has to be a
 *   multiple of the wrap period or the old tag lands somewhere else and the
 *   cell passes against a broken build for the wrong reason. 256 is 2x128 and
 *   1x256, so it recurs against a 7-bit tag and against an 8-bit one; 300,
 *   which is merely "a lot", would have discriminated against neither. The
 *   fix's 63-bit monotonic counter simply advances by 256.
 *
 * Both cells assert the SAME property — a delivery from a previous watch is
 * never reported to a later one — which is the point: with a single snapshot
 * and a non-recurring tag there is one rule, not two special cases.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include <signal.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>

/* Stub: the shim's thread/offload seams reference the Saw allocator, which this
 * probe never reaches. */
void __saw_rt_dealloc(void *ptr, size_t size, size_t align);
void __saw_rt_dealloc(void *ptr, size_t size, size_t align) {
    (void)ptr; (void)size; (void)align;
}

long __saw_signal_number(long tag);
long __saw_signal_watch(long signo);
void __saw_signal_unwatch(long signo);
long __saw_signal_raise(long signo);
long __saw_signal_drain(long signo);

static int failures = 0;
static void check(int ok, const char *what) {
    printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) failures++;
}

/* ---- the scheduling hook ------------------------------------------------
 * Called from inside the real handler, after its snapshot and before its write.
 * Announces that the handler is poised, then waits for permission to proceed.
 * Not async-signal-safe and does not need to be: it exists only to make one
 * legal interleaving deterministic instead of a nanoseconds-wide race.
 */
static pthread_mutex_t hook_m = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t hook_c = PTHREAD_COND_INITIALIZER;
static int hook_armed = 0;    /* pause the next handler that arrives */
static int hook_poised = 0;   /* a handler is waiting inside the hook */
static int hook_release = 0;  /* let it proceed */

void __saw_signal_test_hook(unsigned long long tag) {
    (void)tag;
    pthread_mutex_lock(&hook_m);
    if (!hook_armed) {
        pthread_mutex_unlock(&hook_m);
        return;
    }
    hook_armed = 0;
    hook_poised = 1;
    pthread_cond_broadcast(&hook_c);
    while (!hook_release) pthread_cond_wait(&hook_c, &hook_m);
    pthread_mutex_unlock(&hook_m);
}

/* A thread that exists only to receive the signal, so the handler runs
 * somewhere other than the thread driving the test (whose own condvar wait the
 * handler's hook would otherwise deadlock against). */
static volatile sig_atomic_t victim_ready = 0;
static void *victim(void *arg) {
    (void)arg;
    victim_ready = 1;
    for (;;) {
        struct timespec ts = {0, 1000000};
        nanosleep(&ts, NULL);
    }
    return NULL;
}

static pthread_t victim_thread;
static void start_victim(void) {
    pthread_create(&victim_thread, NULL, victim, NULL);
    while (!victim_ready) { }
}

/* Deliver to the victim and block until its handler is poised in the hook. */
static void deliver_and_wait_poised(long signo) {
    pthread_mutex_lock(&hook_m);
    hook_armed = 1;
    hook_poised = 0;
    hook_release = 0;
    pthread_mutex_unlock(&hook_m);

    pthread_kill(victim_thread, (int)signo);

    pthread_mutex_lock(&hook_m);
    while (!hook_poised) pthread_cond_wait(&hook_c, &hook_m);
    pthread_mutex_unlock(&hook_m);
}

static void release_handler(void) {
    pthread_mutex_lock(&hook_m);
    hook_release = 1;
    pthread_cond_broadcast(&hook_c);
    pthread_mutex_unlock(&hook_m);
    /* Let the write land before anything reads the pipe. */
    struct timespec ts = {0, 30 * 1000 * 1000};
    nanosleep(&ts, NULL);
}

/* Run `cycles` complete unwatch/rewatch rounds while a handler is poised. */
static void cycle_watch(long signo, int cycles) {
    for (int i = 0; i < cycles; i++) {
        __saw_signal_unwatch(signo);
        long r = __saw_signal_watch(signo);
        if (r < 0) {
            printf("     rewatch %d failed: %ld\n", i, r);
            return;
        }
    }
}

static void cell_in_flight_rewatch(int cycles, const char *what) {
    long signo = __saw_signal_number(cycles == 1 ? 5 : 6);   /* User1 / User2 */
    long rd = __saw_signal_watch(signo);
    if (rd < 0) { check(0, what); return; }

    /* A handler for THIS watch is now poised between snapshot and write. */
    deliver_and_wait_poised(signo);

    /* Move the lifecycle on underneath it. */
    cycle_watch(signo, cycles);

    /* Let the old handler write, then ask the CURRENT watch what it has. */
    release_handler();
    long pending = __saw_signal_drain(signo);

    check(pending < 0, what);
    if (pending >= 0) {
        printf("     stale deliveries accepted=%ld after %d rewatch(es)\n",
               pending, cycles);
    }
    __saw_signal_unwatch(signo);
}

/* A control: the same machinery must still report a delivery that really does
 * belong to the current watch, or the cells above would pass by rejecting
 * everything. */
static void cell_current_delivery_is_reported(void) {
    long signo = __saw_signal_number(3);   /* Hangup */
    long rd = __saw_signal_watch(signo);
    if (rd < 0) { check(0, "control: watch acquired"); return; }
    __saw_signal_raise(signo);
    struct timespec ts = {0, 30 * 1000 * 1000};
    nanosleep(&ts, NULL);
    long pending = __saw_signal_drain(signo);
    check(pending > 0, "control: a delivery under the CURRENT watch is reported");
    __saw_signal_unwatch(signo);
}

int main(void) {
    start_victim();
    cell_in_flight_rewatch(
        1, "in-flight handler + ONE rewatch: the stale delivery is rejected");
    cell_in_flight_rewatch(
        256, "in-flight handler + 256 rewatches: the tag has not recurred");
    cell_current_delivery_is_reported();
    if (failures == 0) {
        printf("signal in-flight probe: all cells hold\n");
        return 0;
    }
    printf("signal in-flight probe: %d cell(s) FAILED\n", failures);
    return 1;
}
