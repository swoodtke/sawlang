#!/usr/bin/env python3
"""The one-time comparison of sawc2's parser with the frozen parser (SL-424, contract item 9).

    python compiler/tools/frozen_compare.py              compare, and print the counts
    python compiler/tools/frozen_compare.py --list       also list every disagreement
    python compiler/tools/frozen_compare.py FILE...      compare those files only

It runs over the unchanged part of the language: the files of `tests/corpus/`
that `MIGRATION.tsv` marks `copied` or `reviewed` and whose text is byte for
byte the `examples/` file of the same path, and every tracked `.saw` file of
std, blade and libs. The frozen lexer and parser are called through their
Python API, never through `sawc.py --emit-ast`, which dumps the typed tree and
so would count a file that fails to typecheck as refused. sawc2 runs once, as
`sawc2 parse --dump`, over the whole list.

Where both parsers accept a file, it compares a shape both trees hold (SHAPE,
below), never the full tree. `compiler/tests/parse/FROZEN_COMPARISON.md`
records the result and classifies every disagreement. The check was run once;
after it only the parser corpus's fixtures count, so this is no lane.
"""
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "compiler", "tests", "grammar"))

import build  # noqa: E402
import recognize  # noqa: E402

CORPUS = "tests/corpus"
EXAMPLES = "examples"
MIGRATION = os.path.join(REPO, CORPUS, "MIGRATION.tsv")
UNCHANGED = ("copied", "reviewed")
TREES = ("sawc/std", "blade", "libs")
WORK = os.path.join(REPO, ".build", "frozen-compare")

# SHAPE: what is compared where both parsers accept a file.
#   - every item of the file, and of each inline module's body: its kind, its
#     name and its order;
#   - every function: a top-level `func`, an extension's method or `init`, and
#     a trait requirement: its name, its parameters (a receiver apart) and the
#     statements of its body, a trailing expression counted as one.
# KINDS maps the frozen parser's `Program` list an item lands in to the node
# GRAMMAR.md builds for it; `export` has none, since the grammar refuses it.
KINDS = {
    "functions": ("func", "Func"),
    "structs": ("struct", "Struct"),
    "enums": ("enum", "Enum"),
    "traits": ("trait", "Trait"),
    "extensions": ("extension", "Extension"),
    "type_definitions": ("type-alias", "TypeAlias"),
    "extern_blocks": ("extern", "ExternBlock"),
    "statics": ("static", "Static"),
    "imports": ("import", "Import"),
    "module_decls": ("module", "ModuleDecl"),
    "static_asserts": ("static_assert", "StaticAssert"),
    "exports": ("export", None),
}
NODE_KIND = {node: kind for kind, node in KINDS.values() if node}
# The words a declaration's node prints before its name (README, Leaves).
HEAD_WORDS = {"unsafe", "borrows", "static", "var", "public", "private"}


# ---- the files -----------------------------------------------------------------------

def unchanged_corpus():
    """(the corpus files to compare, the marked files whose text differs from examples/)."""
    keep, differ = [], []
    with open(MIGRATION, encoding="utf-8") as fh:
        rows = [line.rstrip("\n").split("\t") for line in fh][1:]
    for row in rows:
        if len(row) < 2 or not set(row[1].split(",")) & set(UNCHANGED):
            continue
        path = os.path.join(CORPUS, row[0])
        original = os.path.join(EXAMPLES, row[0])
        try:
            with open(os.path.join(REPO, path), "rb") as a, \
                    open(os.path.join(REPO, original), "rb") as b:
                same = a.read() == b.read()
        except OSError:
            same = False
        (keep if same else differ).append(path)
    return keep, differ


def tracked(trees):
    out = subprocess.run(["git", "ls-files", "--"] + ["%s/*.saw" % t for t in trees],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    return sorted(set(out.split()))


# ---- the frozen parser ------------------------------------------------------------------

def frozen_shape(path):
    """(verdict, detail) for one file: ("OK", shape) or ("FAIL", first message)."""
    if os.path.join(REPO, "sawc") not in sys.path:
        sys.path.insert(0, os.path.join(REPO, "sawc"))
    sys.setrecursionlimit(20000)
    from lexer import Lexer
    from parser import Parser

    order = {}

    class Recording(Parser):
        """The frozen parser, noting which `Program` list each item lands in."""

        def _dispatch_toplevel_decl(self, p):
            before = {name: len(getattr(p, name)) for name in KINDS}
            result = super()._dispatch_toplevel_decl(p)
            for name in KINDS:
                if len(getattr(p, name)) > before[name]:
                    order.setdefault(id(p), []).append((name, before[name]))
            return result

    with open(os.path.join(REPO, path), encoding="utf-8") as fh:
        source = fh.read()
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            lexer = Lexer(source)
            tokens = lexer.tokenize()
            program = Recording(tokens, source_file=path,
                                doc_comments=lexer.doc_comments).parse()
    except SyntaxError as exc:
        return "FAIL", str(exc).split("\n")[0]
    except Exception as exc:  # a crash is a refusal too, recorded apart
        return "CRASH", "%s: %s" % (type(exc).__name__, str(exc).split("\n")[0])
    items, funcs = [], []
    frozen_program(program, order, "", items, funcs)
    return "OK", {"items": items, "funcs": funcs}


def block_size(block):
    if block is None:
        return None
    return len(block.statements) + (1 if block.final_expr is not None else 0)


def frozen_params(parameters):
    """The parameters less the receiver, which the frozen parser keeps as one named `self`."""
    return len([p for p in parameters if p.name != "self"])


def frozen_program(program, order, prefix, items, funcs):
    for name, index in order.get(id(program), []):
        node = getattr(program, name)[index]
        kind = KINDS[name][0]
        if name == "imports":
            label = ".".join(node.path)
        elif name == "extensions":
            label = node.struct_name
        elif name in ("extern_blocks", "static_asserts", "exports"):
            label = "-"
        else:
            label = node.name
        items.append("%s%s %s" % (prefix, kind, label))
        if name == "functions":
            funcs.append("%s%s(%d) %s" % (prefix, node.name, frozen_params(node.parameters),
                                          block_size(node.body)))
        elif name == "extensions":
            for m in node.methods:
                funcs.append("%s%s.%s(%d) %s" % (prefix, label, "init" if m.is_init else m.name,
                                                 frozen_params(m.parameters), block_size(m.body)))
        elif name == "traits":
            for m in node.methods:
                funcs.append("%s%s.%s(%d) %s" % (prefix, label, m.name, frozen_params(m.parameters),
                                                 block_size(m.body)))
        elif name == "module_decls" and node.is_inline and node.body is not None:
            frozen_program(node.body, order, prefix + node.name + "::", items, funcs)


# ---- sawc2 -----------------------------------------------------------------------------------

class Node:
    def __init__(self, kind):
        self.kind = kind
        self.children = []  # Node or str

    @property
    def base(self):
        return self.kind.split(".")[0]

    def nodes(self, base=None):
        return [c for c in self.children if isinstance(c, Node) and (base is None or c.base == base)]

    def leaves(self):
        return [c for c in self.children if isinstance(c, str)]


def read_dump(text):
    """The canonical dump's S-expression, as Nodes (README, The canonical dump)."""
    stack, root, i, n = [], None, 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "(":
            j = i + 1
            while j < n and not text[j].isspace() and text[j] != ")":
                j += 1
            node = Node(text[i + 1:j])
            if stack:
                stack[-1].children.append(node)
            else:
                root = node
            stack.append(node)
            i = j
        elif c == ")":
            stack.pop()
            i += 1
        else:
            j = i
            if c == '"':
                j += 1
                while text[j] != '"':
                    j += 2 if text[j] == "\\" else 1
                j += 1
            else:
                while j < n and not text[j].isspace() and text[j] != ")":
                    j += 2 if text[j] == "\\" else 1
            stack[-1].children.append(text[i:j])
            i = j
    return root


def name_of(node):
    """The declared name: the first leaf past the head words, `[]` and `[]=` whole."""
    words = [w for w in node.leaves() if w not in HEAD_WORDS]
    if not words:
        return "-"
    if words[0] == "[":
        return "[]=" if words[2:3] == ["="] else "[]"
    return words[0]


def path_of(node):
    paths = node.nodes("Path")
    return ".".join(paths[0].leaves()) if paths else "-"


def params_of(node):
    return len([p for p in node.nodes("Param") if p.kind != "Param.receiver"])


def body_of(node):
    blocks = node.nodes("Block")
    return str(len(blocks[-1].children)) if blocks else "None"


def sawc2_program(items_node, prefix, items, funcs):
    for item in items_node.nodes():
        if item.base in ("Doc", "Visibility", "Attribute"):
            continue
        inner = item
        if item.base == "Declaration":
            inner = [c for c in item.nodes() if c.base not in ("Doc", "Visibility", "Attribute")][0]
        kind = NODE_KIND.get(inner.base, inner.kind)
        if inner.base == "Import":
            label = path_of(inner)
        elif inner.base == "Extension":
            label = path_of(inner)
        elif inner.base in ("ExternBlock", "StaticAssert"):
            label = "-"
        else:
            label = name_of(inner)
        items.append("%s%s %s" % (prefix, kind, label))
        if inner.base == "Func":
            funcs.append("%s%s(%d) %s" % (prefix, label, params_of(inner), body_of(inner)))
        elif inner.base == "Extension":
            for member in inner.nodes("ExtensionMember"):
                m = [c for c in member.nodes() if c.base in ("Method", "Init")]
                if not m:
                    continue
                m = m[0]
                mname = "init" if m.base == "Init" else name_of(m)
                funcs.append("%s%s.%s(%d) %s" % (prefix, label, mname, params_of(m), body_of(m)))
        elif inner.base == "Trait":
            for r in inner.nodes("Requirement"):
                funcs.append("%s%s.%s(%d) %s" % (prefix, label, name_of(r), params_of(r),
                                                 body_of(r)))
        elif inner.kind == "ModuleDecl.inline":
            sawc2_program(inner, prefix + label + "::", items, funcs)


def sawc2_shapes(paths):
    """{path: (verdict, detail)} from one `sawc2 parse --dump` process."""
    os.makedirs(WORK, exist_ok=True)
    listing = os.path.join(WORK, "inputs.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        fh.write("".join(p + "\n" for p in paths))
    r = subprocess.run([build.SAWC2, "parse", "--dump", "@" + listing], cwd=REPO,
                       capture_output=True)
    records, current = {}, None
    for line in r.stdout.decode("utf-8", "replace").split("\n"):
        if line.startswith("FILE\t"):
            current = []
            records[line[5:]] = current
        elif current is not None:
            current.append(line)
    out = {}
    for path in paths:
        lines = records.get(path)
        if lines is None:
            out[path] = ("NONE", "sawc2 printed no record")
            continue
        errors = [line.split("\t") for line in lines if line.startswith("ERROR\t")]
        if errors:
            out[path] = ("FAIL", "%s at %s: %s" % (errors[0][1], errors[0][2], errors[0][3]))
            continue
        items, funcs = [], []
        sawc2_program(read_dump("\n".join(lines)), "", items, funcs)
        out[path] = ("OK", {"items": items, "funcs": funcs})
    return out


# ---- the comparison ------------------------------------------------------------------------

def first_difference(a, b):
    for n in range(max(len(a), len(b))):
        x = a[n] if n < len(a) else "<end>"
        y = b[n] if n < len(b) else "<end>"
        if x != y:
            return n, x, y
    return None


def compare(paths, jobs):
    results = recognize.run_workers([os.path.abspath(__file__), "--worker"], paths, jobs)
    frozen = {path: tuple(result) for path, result in zip(paths, results)}
    ours = sawc2_shapes(paths)
    rows = []
    for path in paths:
        fv, fd = frozen[path]
        sv, sd = ours[path]
        if fv == "OK" and sv == "OK":
            diffs = []
            for part in ("items", "funcs"):
                d = first_difference(fd[part], sd[part])
                if d is not None:
                    diffs.append("%s #%d: frozen %r, sawc2 %r" % ((part,) + d))
            rows.append((path, "both accept" if not diffs else "shape differs", diffs, fd))
        elif fv != "OK" and sv != "OK":
            rows.append((path, "both refuse", ["frozen: %s" % fd, "sawc2: %s" % sd], None))
        elif fv == "OK":
            rows.append((path, "frozen accepts, sawc2 refuses", ["sawc2: %s" % sd], None))
        else:
            rows.append((path, "frozen refuses, sawc2 accepts",
                         ["frozen%s: %s" % (" crashes" if fv == "CRASH" else "", fd)], None))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help="compare these files only")
    ap.add_argument("--list", action="store_true", help="list every disagreement")
    ap.add_argument("--jobs", type=int, default=recognize.default_jobs())
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.worker:
        for line in sys.stdin:
            sys.stdout.write(json.dumps(frozen_shape(line.rstrip("\n"))) + "\n")
            sys.stdout.flush()
        return 0
    ok, output = build.build_sawc2()
    if not ok:
        print("frozen comparison: sawc2 does not build: %s" % output.strip().split("\n")[-1])
        return 2
    differ = []
    if args.files:
        paths = [os.path.relpath(os.path.abspath(f), REPO) for f in args.files]
    else:
        corpus, differ = unchanged_corpus()
        paths = corpus + tracked(TREES)
    rows = compare(paths, args.jobs)
    counts = {}
    for _, verdict, _, _ in rows:
        counts[verdict] = counts.get(verdict, 0) + 1
    items = sum(len(fd["items"]) for _, v, _, fd in rows if v == "both accept")
    funcs = sum(len(fd["funcs"]) for _, v, _, fd in rows if v == "both accept")
    print("frozen comparison: %d files (%d marked corpus files differ from examples/ and "
          "are left out)" % (len(paths), len(differ)))
    for verdict in ("both accept", "shape differs", "both refuse",
                    "frozen accepts, sawc2 refuses", "frozen refuses, sawc2 accepts"):
        print("  %s: %d" % (verdict, counts.get(verdict, 0)))
    print("  compared where both accept: %d items, %d functions" % (items, funcs))
    for root in (CORPUS,) + TREES:
        mine = [v for p, v, _, _ in rows if p.startswith(root + "/")]
        print("  %s: %d files, %d accepted by both" % (root, len(mine), mine.count("both accept")))
    for path, verdict, detail, _ in rows:
        if verdict == "both accept" or (verdict == "both refuse" and not args.list):
            continue
        if args.list or verdict != "both refuse":
            print("%s: %s" % (verdict, path))
            for line in detail:
                print("    " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
