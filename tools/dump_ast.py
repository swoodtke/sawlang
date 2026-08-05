#!/usr/bin/env python3
"""Canonical AST dump for one `.saw` file (design 126 R11).

The parser-stage counterpart of `tools/dump_tokens.py`: lex + PARSE a file and
emit `sawc/ast_dump.py`'s canonical text. This is what the coming Saw parser
port is diffed against, so it is deliberately PARSE-ONLY -- no typechecking, no
builtin/std merge, no module resolution. `sawc --emit-ast` dumps the typechecked
tree instead (desugar nodes, resolved types, and all of `builtin.saw` merged in),
which is the right thing for debugging and the wrong thing for a parser oracle.

A file that does not lex or parse emits a single ERROR record instead of a tree,
exactly as `dump_tokens.py` does, so the corpus's ~26 deliberate parse-error
examples become positive coverage of error POSITIONS rather than a hole:

    ERROR<TAB>line:col<TAB>message

Usage:
    python tools/dump_ast.py [--ids] <file.saw>

Exit code 0 on a parsed file, 1 on an error record.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "sawc"))

from lexer import Lexer            # noqa: E402
from parser import Parser          # noqa: E402
from ast_dump import ASTDumper     # noqa: E402

_ERR_RE = re.compile(r"at (\d+):(\d+): (.*)", re.DOTALL)


def dump(path: str, ids: bool = False):
    """(records, exit_code). One record per output line."""
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    try:
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        program = Parser(tokens, source_file=path,
                         doc_comments=lexer.doc_comments).parse()
    except SyntaxError as exc:
        m = _ERR_RE.search(str(exc))
        if m:
            line, col, text = m.group(1), m.group(2), m.group(3)
        else:
            line, col, text = "0", "0", str(exc)
        # Only the first reported error: the parser's recovery mode can report
        # several in one message, and the harness compares tag + position.
        text = text.split("\n")[0]
        rec = ("ERROR\t%s:%s\t%s" % (line, col, text)).encode("utf-8")
        return [rec], 1

    dumper = ASTDumper(ids=ids)
    text = dumper.dump(program)
    records = [ln.encode("utf-8") for ln in text.split("\n")]
    # A dispatcher miss means the dump is INCOMPLETE -- surface it as a record
    # so it can never pass unnoticed.
    for miss in dumper.unknown:
        records.append(("UNKNOWN\t%s" % miss).encode("utf-8"))
    return records, 0


def main():
    args = sys.argv[1:]
    ids = False
    if args and args[0] == "--ids":
        ids = True
        args = args[1:]
    if not args:
        sys.stderr.write("usage: dump_ast.py [--ids] <file.saw>\n")
        sys.exit(2)
    records, code = dump(args[0], ids=ids)
    data = b"\n".join(records) + (b"\n" if records else b"")
    sys.stdout.buffer.write(data)
    sys.exit(code)


if __name__ == "__main__":
    main()
