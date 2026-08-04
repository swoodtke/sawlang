#!/usr/bin/env python3
"""Dump the sawc Python lexer's tokens in the canonical sawlex format.

Design 116 (self-hosting lexer pilot) testing tool. Emits, for a `.saw` file,
one record per token:

    KIND<TAB>line:col<TAB>escaped-text[<TAB>suffix]

and, if the lexer rejects the file, a single record

    ERROR<TAB>line:col<TAB>message

exiting nonzero. The Saw port (`selfhost/lexer`) emits the byte-identical format
via `format_token`/`format_error`; `tools/lexdiff.py` diffs the two dumps over
the whole tracked-`.saw` corpus (zero mismatches is the acceptance bar).

This tool imports the in-tree lexer directly and makes NO sawc changes.

Usage:
    python tools/dump_tokens.py <file.saw>
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "sawc"))

from lexer import Lexer  # noqa: E402


# `Lexer.error` raises `SyntaxError("Lexer error at L:C: msg")`; some deeper
# range/hash sites raise the same shape directly. Parse the position back out.
_ERR_RE = re.compile(r"Lexer error at (\d+):(\d+): (.*)", re.DOTALL)


def escape_text(value: str) -> bytes:
    """Byte-level escaper — identical scheme to `escape_text` in lib.saw.

    Operates on the token value's UTF-8 bytes so the Saw port (which iterates
    `String.bytes()`) produces byte-for-byte identical output. Raw bytes >= 0x80
    are emitted verbatim.
    """
    out = bytearray()
    for b in value.encode("utf-8"):
        if b == 0x5C:       # backslash
            out += b"\\\\"
        elif b == 0x0A:     # newline
            out += b"\\n"
        elif b == 0x09:     # tab
            out += b"\\t"
        elif b == 0x0D:     # carriage return
            out += b"\\r"
        elif b == 0x00:     # NUL
            out += b"\\0"
        elif b < 0x20 or b == 0x7F:
            out += ("\\x%02x" % b).encode("ascii")
        else:
            out.append(b)
    return bytes(out)


def format_token(tok) -> bytes:
    # NOTE (DF-116a): the Python Token also carries a fixed-width integer `suffix`,
    # but the Saw port cannot surface it (an Optional<String> miscompile — see
    # designs/todo.md DF-116a). To keep the two dumps comparable, BOTH omit the
    # suffix column; suffixed literals still compare on kind/position/value.
    head = ("%s\t%d:%d\t" % (tok.type.name, tok.line, tok.column)).encode("ascii")
    return head + escape_text(tok.value)


def dump(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    lexer = Lexer(source)
    try:
        tokens = lexer.tokenize()
    except SyntaxError as exc:
        m = _ERR_RE.search(str(exc))
        if m:
            line, col, text = m.group(1), m.group(2), m.group(3)
        else:
            line, col, text = "0", "0", str(exc)
        # Match the Saw port: on error, emit ONLY the ERROR record.
        rec = ("ERROR\t%s:%s\t%s" % (line, col, text)).encode("utf-8")
        return [rec], 1
    return [format_token(t) for t in tokens], 0


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("usage: dump_tokens.py <file.saw>\n")
        sys.exit(2)
    records, code = dump(sys.argv[1])
    data = b"\n".join(records) + (b"\n" if records else b"")
    sys.stdout.buffer.write(data)
    sys.exit(code)


if __name__ == "__main__":
    main()
