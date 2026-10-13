"""The gate's one worker budget, which every runner and lane pool draws on.

    SAW_GATE_JOBS=N    at most N workers busy at once; 1 runs serially

The rule: the gate never keeps more than 75% of the machine's cores busy,
`max(1, floor(0.75 * os.cpu_count()))`, and that ceiling is a total over
everything the gate runs at once, in every process. An explicit SAW_GATE_JOBS
is clamped to the ceiling, never raised past it. The total is held by tokens
(`budget`): the outermost runner owns one implicitly and makes the rest, every
process it starts inherits them, and a worker beyond a process's first takes
one (`map_ordered`, `try_acquire`), so concurrently scheduled lanes share one
budget and never multiply it. Pinned by compiler/tests/parallel_order.py.

ENTRY POINTS:
  ceiling
  jobs
  budget
  try_acquire
  acquire
  release
  map_ordered
  child_env
"""
import contextlib
import fcntl
import os
import random
import shutil
import tempfile
import threading
import time

VARIABLE = "SAW_GATE_JOBS"
# The directory of token files a budget is held in; a token is an exclusive
# flock on one of them, which the kernel drops when its holder dies.
TOKENS = "SAW_GATE_TOKENS"


def ceiling(cpus=None):
    """Three quarters of `cpus` (the machine's core count when None), rounded
    down, and never less than one."""
    if cpus is None:
        cpus = os.cpu_count() or 1
    return max(1, cpus * 3 // 4)


def jobs(environ=None, cpus=None):
    """The most workers one pool may run: SAW_GATE_JOBS clamped to
    `ceiling(cpus)`, or the ceiling when it is unset. A value that is not a
    positive count is an error, never a silent default."""
    environ = os.environ if environ is None else environ
    top = ceiling(cpus)
    value = environ.get(VARIABLE, "").strip()
    if not value:
        return top
    if not value.isdigit() or int(value) < 1:
        raise SystemExit("%s is %r; it is a positive count of workers" % (VARIABLE, value))
    return min(int(value), top)


def child_env(count, base=None):
    """A copy of the environment (`base`, else this process's) whose
    SAW_GATE_JOBS lets a child run at most `count` workers."""
    env = dict(os.environ if base is None else base)
    env[VARIABLE] = str(count)
    return env


@contextlib.contextmanager
def budget():
    """The budget this process draws on: the one it inherited, or, in the
    outermost runner, a new one of `jobs()` tokens, the first of them this
    process's own, made for the block and removed after it."""
    if os.environ.get(TOKENS):
        yield
        return
    directory = tempfile.mkdtemp(prefix="saw-gate-tokens-")
    try:
        for k in range(jobs() - 1):
            open(os.path.join(directory, "token-%d" % k), "w").close()
        os.environ[TOKENS] = directory
        yield
    finally:
        os.environ.pop(TOKENS, None)
        shutil.rmtree(directory, ignore_errors=True)


def try_acquire():
    """A token, or None when every one is held or there is no budget."""
    directory = os.environ.get(TOKENS)
    if not directory:
        return None
    try:
        names = os.listdir(directory)
    except OSError:
        return None
    random.shuffle(names)
    for name in names:
        try:
            fd = os.open(os.path.join(directory, name), os.O_RDONLY)
        except OSError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            os.close(fd)
    return None


def acquire(until=None):
    """A token, waiting for one; None once `until()` is true first."""
    pause = 0.01
    while True:
        if until is not None and until():
            return None
        token = try_acquire()
        if token is not None:
            return token
        time.sleep(pause)
        pause = min(pause * 2, 0.1)


def release(token):
    if token is not None:
        fcntl.flock(token, fcntl.LOCK_UN)
        os.close(token)


def map_ordered(fn, items, most=None):
    """[fn(item) for item in items], computed by up to `jobs()` threads (and
    at most `most`) and returned in the order of `items`. The first thread
    runs on the token the caller holds; each other one takes a token per
    item, so a pool never waits for a token it cannot get. The first
    exception, in item order, is raised once every thread has stopped."""
    items = list(items)
    width = min(jobs(), most or len(items), len(items))
    if width <= 1:
        return [fn(item) for item in items]
    results = [None] * len(items)
    errors = [None] * len(items)
    lock = threading.Lock()
    taken = [0]

    def take():
        with lock:
            k = taken[0]
            if k >= len(items):
                return None
            taken[0] = k + 1
            return k

    def done():
        with lock:
            return taken[0] >= len(items)

    def call(k):
        try:
            results[k] = fn(items[k])
        except BaseException as e:  # raised in order below
            errors[k] = e

    def worker(own_token):
        while True:
            token = None if own_token else acquire(until=done)
            if not own_token and token is None:
                return
            k = take()
            try:
                if k is not None:
                    call(k)
            finally:
                release(token)
            if k is None:
                return

    with budget():
        threads = [threading.Thread(target=worker, args=(k == 0,), daemon=True) for k in range(width)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    for e in errors:
        if e is not None:
            raise e
    return results
