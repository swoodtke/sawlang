#!/usr/bin/env python3
"""Generate a scheduling-hook copy of sawc/rt/shim.c for the signal race pins.

Design 272 unit 3 / SL-228 review r3. Two of the pins have to PAUSE A REAL
SIGNAL HANDLER at one exact point — after it takes its state snapshot and
before it writes — and neither Saw nor C-from-outside can do that to code it
does not compile. So the pins compile the shim themselves, with one hook call
inserted at a marker that lives in the real source.

GENERATE, NEVER FORK. The output is `sawc/rt/shim.c` byte for byte except for
one substituted line. If the marker is missing, or appears more than once, this
exits non-zero rather than emitting something that merely resembles the runtime
— a pin built against a stale transcription of the code under test pins the
transcription, which is the failure mode this file exists to prevent.

Usage:  signal_hook_shim.py <shim.c> <output.c>
"""
import sys

# The inert comment the real shim carries, and what it becomes.
MARKER = "/* SAW_SIGNAL_TEST_HOOK */"
HOOK_DECL = """
/* ---- GENERATED: scheduling hook (tools/signal_hook_shim.py) -------------
 * Defined by the pin. Called from inside the real handler, after its state
 * snapshot and before its write — the one interleaving point that decides
 * whether a late delivery can be mistaken for a current one. The hook only
 * FORCES a legal schedule; every piece of lifecycle and notification logic
 * below is the shipped code, unmodified.
 */
extern void __saw_signal_test_hook(unsigned long long tag);
"""
HOOK_CALL = "__saw_signal_test_hook((unsigned long long)tag);"


def main(argv):
    if len(argv) != 3:
        print("usage: signal_hook_shim.py <shim.c> <output.c>", file=sys.stderr)
        return 2
    src_path, out_path = argv[1], argv[2]
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    count = src.count(MARKER)
    if count != 1:
        print(
            "signal_hook_shim: expected exactly one %s in %s, found %d.\n"
            "The pins cannot be generated against a source whose hook point has "
            "moved or been removed. Restore the marker, or update this generator "
            "deliberately — do NOT hand-edit a copy of the shim."
            % (MARKER, src_path, count),
            file=sys.stderr,
        )
        return 1

    # The declaration goes immediately before the handler that uses it, which is
    # the function containing the marker. Inserting at the marker's enclosing
    # function keeps the edit to one region.
    hooked = src.replace(MARKER, HOOK_CALL, 1)

    anchor = "static void __saw_sig_handler(int signo) {"
    if hooked.count(anchor) != 1:
        print(
            "signal_hook_shim: could not find the handler to declare the hook "
            "ahead of (%r). The generator and the shim have drifted." % anchor,
            file=sys.stderr,
        )
        return 1
    hooked = hooked.replace(anchor, HOOK_DECL + "\n" + anchor, 1)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(hooked)
    print("signal_hook_shim: generated %s from %s (1 hook)" % (out_path, src_path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
