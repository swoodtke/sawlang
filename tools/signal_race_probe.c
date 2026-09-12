/* Design 272 unit 3 — signal-bridge concurrency pins that need NO hook
 * (SL-228 review r1, scope corrected after r3).
 *
 * These cells are expressible in C against the shim EXACTLY AS SHIPPED: they
 * link `sawc/rt/shim.c` itself, never a copy, because a pin built against a
 * transcription of the code under test pins the transcription. What they can
 * therefore NOT do is stop a handler in the middle — nothing outside the
 * runtime can. Every cell below says which of the two it is.
 *
 * The cells that DO pause a real handler live in
 * `tools/signal_inflight_probe.c`, which links a generated hook copy. The split
 * is deliberate: everything provable without touching the runtime source is
 * proved here, and only the genuinely unreachable interleavings pay for a
 * generated build.
 *
 * `examples/signal_concurrency_pins.saw` builds and runs BOTH, so they gate in
 * the ordinary suite rather than living as files somebody has to remember.
 *
 * Run with no arguments. Exit 0 = every cell holds.
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

/* The shim also carries the thread/offload seams, which reference the Saw
 * runtime's allocator. This probe links only the shim, so the allocator gets a
 * stub: nothing here reaches the code path that calls it, and a stub is clearer
 * than relying on the linker to dead-strip it. */
void __saw_rt_dealloc(void *ptr, size_t size, size_t align);
void __saw_rt_dealloc(void *ptr, size_t size, size_t align) {
    (void)ptr; (void)size; (void)align;
}

/* The shim's signal surface. */
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

/* ---------------------------------------------------------------- cell 1 ---
 * CONCURRENT ACQUISITION. Two threads race `watch` on ONE signal. Exactly one
 * must win; the other must get -2 (AlreadyExists). Before the fix both won,
 * overwriting each other's descriptor and saved-disposition writes — and a
 * saved "previous" disposition could be Saw's own handler, so dropping either
 * handle restored the wrong thing.
 *
 * No gate is needed now that the transaction is serialized: the two threads are
 * started together and hammer the same signal, and the assertion is on the
 * RESULTS rather than on hitting a particular interleaving. Repeated, because
 * one round of a race proves little.
 */
static long race_result[2];
static long race_signo;

/* macOS has no pthread_barrier; a condvar gate serves and is portable. */
static pthread_mutex_t bar_m = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t bar_c = PTHREAD_COND_INITIALIZER;
static int bar_count = 0;
static int bar_round = 0;

static void bar_wait(int parties) {
    pthread_mutex_lock(&bar_m);
    int round = bar_round;
    if (++bar_count == parties) {
        bar_count = 0;
        bar_round++;
        pthread_cond_broadcast(&bar_c);
    } else {
        while (round == bar_round) pthread_cond_wait(&bar_c, &bar_m);
    }
    pthread_mutex_unlock(&bar_m);
}

static void *race_watcher(void *arg) {
    long i = (long)arg;
    bar_wait(2);
    race_result[i] = __saw_signal_watch(race_signo);
    return NULL;
}

static void cell_concurrent_acquisition(void) {
    race_signo = __saw_signal_number(5);   /* User1 */
    int all_good = 1;
    for (int round = 0; round < 200; round++) {
        race_result[0] = race_result[1] = -99;
        pthread_t a, b;
        pthread_create(&a, NULL, race_watcher, (void *)0);
        pthread_create(&b, NULL, race_watcher, (void *)1);
        pthread_join(a, NULL);
        pthread_join(b, NULL);

        int winners = (race_result[0] >= 0) + (race_result[1] >= 0);
        int refusals = (race_result[0] == -2) + (race_result[1] == -2);
        if (winners != 1 || refusals != 1) {
            printf("     round %d: results %ld %ld (want exactly one >=0 and one -2)\n",
                   round, race_result[0], race_result[1]);
            all_good = 0;
            break;
        }
        __saw_signal_unwatch(race_signo);
    }
    check(all_good, "concurrent acquisition: exactly one watcher wins, the other gets AlreadyExists");
}

/* ---------------------------------------------------------------- cell 2 ---
 * THE DESCRIPTOR IS NEVER RECLAIMED. This cell PAUSES NO HANDLER — said plainly
 * because an earlier version of this comment described a pause it does not
 * perform, which the r3 review caught. What it asserts is the PRECONDITION of
 * the original bug rather than the bug itself.
 *
 * The original failure was: a handler past its descriptor load, a teardown that
 * closes the pipe, an unrelated resource inheriting the number, and the delayed
 * write landing in it. Every step after the first needs the descriptor to be
 * FREE. So this takes the watch's descriptor, unwatches, opens several unrelated
 * pipes, and checks that none of them was handed that number back. If teardown
 * still closed the pipe, the first of them would get it — and the rest of the
 * bug would follow. Removing the precondition is the fix, and the precondition
 * is what is directly observable without compiling a hook into the runtime.
 *
 * The bug ITSELF — a real handler paused mid-flight while the lifecycle moves
 * underneath it — is pinned in `tools/signal_inflight_probe.c`, which links a
 * generated hook copy of the shim and can therefore stop a handler where this
 * cell cannot.
 */
static void cell_descriptor_is_never_reclaimed(void) {
    long signo = __saw_signal_number(6);   /* User2 */
    long rd = __saw_signal_watch(signo);
    check(rd >= 0, "teardown pin: watch acquired");
    if (rd < 0) return;

    /* The write end is the read end's sibling; both must stay ours. Probe by
     * number: anything the process opens next must avoid them. */
    int watch_rd = (int)rd;

    __saw_signal_unwatch(signo);

    /* Open several unrelated pipes. If unwatch had closed the watch pipe, the
     * first of these would be handed its descriptor numbers back. */
    int reused = 0;
    int fds[8][2];
    int n = 0;
    for (; n < 8; n++) {
        if (pipe(fds[n]) != 0) break;
        if (fds[n][0] == watch_rd || fds[n][1] == watch_rd) reused = 1;
    }
    for (int i = 0; i < n; i++) { close(fds[i][0]); close(fds[i][1]); }

    check(!reused,
          "teardown pin: the watch descriptor is NOT reclaimed, so no later "
          "resource can inherit its number");

    /* And the watch is re-acquirable, which is what says teardown released the
     * CLAIM without releasing the descriptor. */
    long again = __saw_signal_watch(signo);
    check(again >= 0, "teardown pin: the signal can be watched again after teardown");
    check(again == rd, "teardown pin: the re-watch reuses the SAME process-lifetime pipe");
    if (again >= 0) __saw_signal_unwatch(signo);
}

/* ---------------------------------------------------------------- cell 3 ---
 * A SETTLED STALE DELIVERY IS NOT REPORTED AS A FRESH ONE. Scope stated
 * exactly, because the r3 review found the earlier comment claimed more than
 * the code does: the write here COMPLETES BEFORE the teardown. No handler is in
 * flight across the generation change, so this is the easy half — a byte that
 * was already sitting in the pipe when the watch ended must not be reported to
 * the next watch.
 *
 * The hard half — a handler paused between its snapshot and its write while the
 * watch is torn down and re-established — is `tools/signal_inflight_probe.c`.
 * That one needs a hook inside the handler; this one does not, and is kept
 * because it covers the settled case with no generated source at all.
 */
static void cell_stale_delivery_is_discarded(void) {
    long signo = __saw_signal_number(6);   /* User2 */
    long rd = __saw_signal_watch(signo);
    if (rd < 0) { check(0, "stale pin: watch acquired"); return; }

    __saw_signal_raise(signo);
    /* Let the handler run. */
    struct timespec ts = {0, 20 * 1000 * 1000};
    nanosleep(&ts, NULL);

    long pending = __saw_signal_drain(signo);
    check(pending > 0, "stale pin: a delivery under the CURRENT watch is reported");

    /* Now leave a byte in the pipe and tear down under it. */
    __saw_signal_raise(signo);
    nanosleep(&ts, NULL);
    __saw_signal_unwatch(signo);

    long again = __saw_signal_watch(signo);
    if (again < 0) { check(0, "stale pin: re-watch acquired"); return; }
    long stale = __saw_signal_drain(signo);
    check(stale < 0,
          "stale pin: a byte from a PREVIOUS watch is discarded, not reported "
          "as a delivery");
    __saw_signal_unwatch(signo);
}

int main(void) {
    cell_concurrent_acquisition();
    cell_descriptor_is_never_reclaimed();
    cell_stale_delivery_is_discarded();
    if (failures == 0) {
        printf("signal race probe: all cells hold\n");
        return 0;
    }
    printf("signal race probe: %d cell(s) FAILED\n", failures);
    return 1;
}
