"""Handing a child's captured output on, whole.

A wrapper that stands where a lane expects sawc (the fixpoint lane's twin,
`parallel_order.py`'s injector) captures the child's output and writes it to
its own standard streams. One `write` is not enough: a raw stream, which is
what `sys.stdout.buffer` is under `PYTHONUNBUFFERED`, takes part of a large
write and returns how much, and on macOS one call takes less than 2 GiB.
"""


def write_all(stream, data):
    """Every byte of `data` written to the binary stream `stream`, in as many
    writes as the stream needs, then flushed. A stream that takes nothing
    (a non-blocking one that would block) is an error, never a silent stop."""
    view = memoryview(data)
    while len(view):
        took = stream.write(view)
        if not took:
            raise OSError("the stream took %r of the %d bytes left to hand on" % (took, len(view)))
        view = view[took:]
    stream.flush()


class _Sipping:
    """A stream that takes at most `sip` bytes a write, as a raw one does."""

    def __init__(self, sip):
        self.sip = sip
        self.got = bytearray()
        self.writes = 0

    def write(self, data):
        took = bytes(data[:self.sip])
        self.got += took
        self.writes += 1
        return len(took) if self.sip else None

    def flush(self):
        pass


def check(failures, counts):
    """`write_all` over a stream that takes three bytes a write hands on every
    byte in order; over one that takes none it raises."""
    data = bytes(range(256)) * 5
    stream = _Sipping(3)
    write_all(stream, data)
    if bytes(stream.got) != data or stream.writes < len(data) // 3:
        failures.append("hand_on: a stream taking 3 bytes a write got %d of %d bytes in %d writes"
                        % (len(stream.got), len(data), stream.writes))
        return
    try:
        write_all(_Sipping(0), data)
    except OSError:
        counts["hand-on cases"] = counts.get("hand-on cases", 0) + 2
        return
    failures.append("hand_on: a stream that takes nothing is not an error")
