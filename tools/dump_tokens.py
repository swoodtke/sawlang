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

With `--docs` (design 121) it emits the doc-comment TRIVIA instead, one record per
captured `///`/`//!` line:

    DOC<TAB>line:col<TAB>kind<TAB>escaped-text

Doc trivia never appears in the default dump, so the design-116 parity baselines
are untouched.

This tool imports the in-tree lexer directly and makes NO sawc changes.

Usage:
    python tools/dump_tokens.py [--docs] <file.saw>
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
    # The 4th column is the fixed-width integer suffix (e.g. `u8` for `255u8`),
    # present only for a suffixed integer literal; every other token stops at the
    # escaped text. The Saw port's `format_token` emits the identical shape (the
    # DF-116a miscompile that had stopped the suffix unit is fixed — design 119
    # Part D).
    head = ("%s\t%d:%d\t" % (tok.type.name, tok.line, tok.column)).encode("ascii")
    rec = head + escape_text(tok.value)
    if getattr(tok, "suffix", None) is not None:
        rec += ("\t%s" % tok.suffix).encode("ascii")
    return rec


def format_doc(doc) -> bytes:
    # Design 121 doc-trivia record, one per captured `///`/`//!` LINE:
    #   DOC<TAB>line:col<TAB>kind<TAB>escaped-text
    # where kind is `doc` (`///`) or `module` (`//!`). The Saw port's
    # `format_doc` emits the identical shape; `tools/lexdiff.py --docs` diffs the
    # two over the corpus. Doc trivia never enters the default token dump.
    head = ("DOC\t%d:%d\t%s\t" % (doc.line, doc.column, doc.kind)).encode("ascii")
    return head + escape_text(doc.text)


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


def dump_docs(path: str):
    """Design 121 `--docs` mode: emit ONLY the doc-trivia records (in source
    order), or a single ERROR record if the file does not lex. The token stream
    itself is not emitted here — doc trivia is the whole payload."""
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    lexer = Lexer(source)
    try:
        lexer.tokenize()
    except SyntaxError as exc:
        m = _ERR_RE.search(str(exc))
        if m:
            line, col, text = m.group(1), m.group(2), m.group(3)
        else:
            line, col, text = "0", "0", str(exc)
        rec = ("ERROR\t%s:%s\t%s" % (line, col, text)).encode("utf-8")
        return [rec], 1
    return [format_doc(d) for d in lexer.doc_comments], 0


def main():
    args = sys.argv[1:]
    docs_mode = False
    if args and args[0] == "--docs":
        docs_mode = True
        args = args[1:]
    if not args:
        sys.stderr.write("usage: dump_tokens.py [--docs] <file.saw>\n")
        sys.exit(2)
    records, code = (dump_docs(args[0]) if docs_mode else dump(args[0]))
    data = b"\n".join(records) + (b"\n" if records else b"")
    sys.stdout.buffer.write(data)
    sys.exit(code)


if __name__ == "__main__":
    main()
