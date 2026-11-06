#!/usr/bin/env python3
"""Write the front cache's per-layer slicer, `compiler/mono/src/frontparts.saw`,
from the front-end stages' struct declarations (`--check`: fail when stale).

Every `Vector` reachable from `FrontCut` is a table, appended to, whose layer
part is its suffix between the layer's watermarks; every other leaf is a
scalar. THE RULE: a field written by index below its layer's watermark must
carry the marker `// front: rewritten in place` at its declaration, which
makes its part the entries changed against a snapshot; every hash index's
`heads` and every `TcMemo` field is rewritten in place by rule; a field reset
or cut back counts as written. The verify pins (`SAWC_FRONT_VERIFY=1`) fail on
a missing marker (SL-955 unit 4b).
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, "compiler", "mono", "src", "frontparts.saw")
MARKER = "// front: rewritten in place"
# A field whose state is this process's alone, which no part carries: its
# type serializes as nothing.
LOCAL = "// front: process-local"
# The packages whose structs the front end's state is made of.
PACKAGES = (("sawresolve", "compiler/resolve/src"), ("sawtypecheck", "compiler/typecheck/src"),
            ("sawmir", "compiler/mir/src"), ("saweval", "compiler/eval/src"),
            ("sawborrowck", "compiler/borrowck/src"), ("sawdrops", "compiler/drops/src"),
            ("sawmono", "compiler/mono/src"), ("sawparse", "compiler/parse/src"),
            ("sawlex", "compiler/lex/src"))
DECL = re.compile(r"^(?:public(?:\([a-z]+\))?\s+)?(?:borrows\s+)?(?:unsafe\s+)?(struct|enum)\s+(\w+)"
                  r"(?:<[^>{]*>)?\s*(?::\s*(\w+)\s*)?\{(.*?)^\}", re.M | re.S)
FIELD = re.compile(r"^\s*(?:private\s+)?(\w+)\s*:\s*([^/\n]+?)\s*(?://.*)?$")
IDENT = re.compile(r"[A-Za-z_]\w*")
BUILTIN = {"Int", "UInt", "Bool", "String", "Vector", "Optional", "Int8", "Int16", "Int32", "Int64", "UInt8",
           "UInt16", "UInt32", "UInt64", "Byte", "Float"}
# Element types a changed entry is found for by comparing, each by a
# function of its own, since a generic `==` may suspend and the compiler's
# source is sync; a raw-backed enum compares its backing (BACKINGS, filled by
# `load`). A rewritten table of any other element type is written whole.
COMPARED = {"Int", "Bool", "String"}
BACKINGS = {}


def load():
    """{type: (module, fields)} for every struct, and {type: module} for every
    enum, of the front end's packages; a field is (name, type, marked)."""
    structs, modules = {}, {}
    for package, rel in PACKAGES:
        root = os.path.join(REPO, rel)
        for dirpath, _, files in sorted(os.walk(root)):
            for f in sorted(files):
                if not f.endswith(".saw") or f == "frontparts.saw":
                    continue
                path = os.path.join(dirpath, f)
                stem = os.path.relpath(path, root)[:-4]
                module = package if stem == "lib" else package + "." + stem.replace(os.sep, ".")
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                for m in DECL.finditer(text):
                    kind, name, backing, body = m.group(1), m.group(2), m.group(3), m.group(4)
                    if name in modules:
                        continue
                    modules[name] = module
                    if kind == "enum" and backing:
                        BACKINGS[name] = backing
                    if kind == "struct":
                        fields = []
                        for line in body.split("\n"):
                            fm = FIELD.match(line)
                            if fm and not line.strip().startswith("//"):
                                if LOCAL not in line:
                                    fields.append((fm.group(1), fm.group(2).strip().rstrip(","), MARKER in line))
                        structs[name] = fields
    return structs, modules


def walk(structs, owner, path, tables, scalars, unmarked):
    for name, ftype, marked in structs[owner]:
        p = path + [name]
        vector = re.match(r"^Vector<(.+)>$", ftype)
        base = re.sub(r"<.*>$", "", ftype)
        if vector:
            if "%s.%s" % (owner, name) == unmarked:
                if not marked:
                    raise SystemExit("front parts: %s carries no marker to leave out" % unmarked)
                marked = False
            rewritten = marked or name == "heads" or owner == "TcMemo"
            tables.append((".".join(p), vector.group(1), rewritten))
        elif base in structs and not ftype.endswith("?"):
            walk(structs, base, p, tables, scalars, unmarked)
        else:
            scalars.append((".".join(p), ftype))


def compares(t):
    """Whether a rewritten table of element type `t` is diffed entry by entry."""
    return t in COMPARED or t in BACKINGS


# The most fields a piece of the part holds. A constructor's labeled
# arguments and a function's statements cost the checker more than linearly,
# so the slicer is cut into pieces of this size (SL-955 unit 4b).
CHUNK = 32


def chunked(tables, scalars):
    """The entries, ("t", index, path, type, rewritten) or ("v", index, path,
    type), grouped by owning struct in walk order and packed into pieces of
    at most CHUNK; an owner with more is split across pieces."""
    groups, order = {}, []
    entries = [("t", i, p, t, r) for i, (p, t, r) in enumerate(tables)]
    entries += [("v", k, p, t) for k, (p, t) in enumerate(scalars)]
    for e in entries:
        owner = e[2].rsplit(".", 1)[0] if "." in e[2] else ""
        if owner not in groups:
            groups[owner] = []
            order.append(owner)
        groups[owner].append(e)
    chunks = [[]]
    for owner in order:
        group = groups[owner]
        while group:
            room = CHUNK - len(chunks[-1])
            if room == 0 or (len(group) <= CHUNK and len(group) > room):
                chunks.append([])
                room = CHUNK
            chunks[-1].extend(group[:room])
            group = group[room:]
    return [c for c in chunks if c]


def chunk_snaps(chunk):
    """The entries of `chunk` a snapshot holds: its rewritten tables and its
    scalars."""
    return [e for e in chunk if e[0] == "v" or e[4]]


def render_chunk(add, n, chunk, spell):
    """Piece `n` of the slicer: its part, its snapshot, and the functions each
    whole-part function calls for it."""
    snaps = chunk_snaps(chunk)
    first = chunk[0][2].rsplit(".", 1)[0] if "." in chunk[0][2] else "FrontCut"
    add("// Piece %d of the slicer, from `%s` on." % (n, first))
    add("public struct FrontPart%d {" % n)
    for e in chunk:
        if e[0] == "t":
            add("    t%d: %s<%s>" % (e[1], "FrontRewrite" if e[4] else "Vector", spell(e[3])))
        else:
            add("    v%d: %s" % (e[1], spell(e[3])))
    add("}")
    add("")
    add("extension FrontPart%d: NoCopy {}" % n)
    add("")
    add("@synthesize")
    add("extension FrontPart%d: Serialize {}" % n)
    add("@synthesize")
    add("extension FrontPart%d: Deserialize {}" % n)
    add("")
    if snaps:
        add("public struct FrontSnap%d {" % n)
        for e in snaps:
            if e[0] == "t":
                add("    r%d: Vector<%s>" % (e[1], spell(e[3])))
            else:
                add("    v%d: %s" % (e[1], spell(e[3])))
        add("}")
        add("")
        add("extension FrontSnap%d: NoCopy {}" % n)
        add("")
        add("func front_snapshot_%d(c: &FrontCut) -> FrontSnap%d {" % (n, n))
        fields = ["r%d: front_copy(&c.%s)" % (e[1], e[2]) if e[0] == "t" else "v%d: c.%s" % (e[1], e[2])
                  for e in snaps]
        add("    FrontSnap%d(" % n + (",\n" + " " * (14 + len(str(n)))).join(fields) + ")")
        add("}")
        add("")
    add("func front_lengths_%d(c: &FrontCut, out: &var Vector<Int>) {" % n)
    for e in chunk:
        if e[0] == "t":
            add("    out[%d] = c.%s.len()" % (e[1], e[2]))
    add("}")
    add("")
    tail = ",\n    before: &FrontSnap%d, after: &FrontSnap%d" % (n, n) if snaps else ""
    add("func front_make_%d(c: &FrontCut, lo: &Vector<Int>, hi: &Vector<Int>%s) -> FrontPart%d {" % (n, tail, n))
    fields = []
    for e in chunk:
        if e[0] == "v":
            fields.append("v%d: after.v%d" % (e[1], e[1]))
        elif e[4] and compares(e[3]):
            fields.append("t%d: front_rewrite_%s(&before.r%d, &after.r%d)" % (e[1], e[3], e[1], e[1]))
        elif e[4]:
            fields.append("t%d: front_rewrite_whole(&after.r%d)" % (e[1], e[1]))
        else:
            fields.append("t%d: front_suffix(&c.%s, lo[%d], hi[%d])" % (e[1], e[2], e[1], e[1]))
    add("    FrontPart%d(" % n + (",\n" + " " * (14 + len(str(n)))).join(fields) + ")")
    add("}")
    add("")
    add("func front_shrunk_%d(c: &FrontCut, hi: &Vector<Int>) -> String {" % n)
    for e in chunk:
        if e[0] == "t" and not e[4]:
            add("    if c.%s.len() < hi[%d] {" % (e[2], e[1]))
            add("        return \"%s\"" % e[2])
            add("    }")
    add("    \"\"")
    add("}")
    add("")
    add("func front_apply_%d(c: &var FrontCut, part: &FrontPart%d) {" % (n, n))
    for e in chunk:
        if e[0] == "v":
            add("    c.%s = part.v%d" % (e[2], e[1]))
        elif e[4]:
            add("    front_rewrite_apply(&var c.%s, &part.t%d)" % (e[2], e[1]))
        else:
            add("    front_append(&var c.%s, &part.t%d)" % (e[2], e[1]))
    add("}")
    add("")


def render(unmarked=None):
    """The slicer's text; with `unmarked`, a field `Type.field`, as though that
    field's marker were missing, for the fault-injection pin alone."""
    structs, modules = load()
    tables, scalars = [], []
    walk(structs, "FrontCut", [], tables, scalars, unmarked)
    used = {}

    def spell(t):
        def rep(m):
            n = m.group(0)
            if n in BUILTIN or n not in modules:
                return n
            used[n] = modules[n]
            return "T_" + n
        t = IDENT.sub(rep, t)
        return "Optional<%s>" % t[:-1] if t.endswith("?") else t

    chunks = chunked(tables, scalars)
    body = []
    add = body.append
    add("// The number of tables `front_part_lengths` measures.")
    add("public func front_part_tables() -> Int { %d }" % len(tables))
    add("")
    for n, chunk in enumerate(chunks):
        render_chunk(add, n, chunk, spell)
    snapped = [n for n, chunk in enumerate(chunks) if chunk_snaps(chunk)]
    add("// Each table's length, by table index, which the pieces do not follow: a")
    add("// layer's watermarks.")
    add("public func front_part_lengths(c: &FrontCut) -> Vector<Int> {")
    add("    var out = Vector<Int>()")
    add("    var k = 0")
    add("    while k < %d {" % len(tables))
    add("        try! out.push(0)")
    add("        k = k + 1")
    add("    }")
    for n in range(len(chunks)):
        add("    front_lengths_%d(&c, &var out)" % n)
    add("    move out")
    add("}")
    add("")
    add("// The rewritten tables and the scalars as a layer leaves them.")
    add("public struct FrontSnap {")
    for n in snapped:
        add("    s%d: FrontSnap%d" % (n, n))
    add("}")
    add("")
    add("extension FrontSnap: NoCopy {}")
    add("")
    add("public func front_part_snapshot(c: &FrontCut) -> FrontSnap {")
    add("    FrontSnap(" + ",\n              ".join("s%d: front_snapshot_%d(&c)" % (n, n) for n in snapped) + ")")
    add("}")
    add("")
    add("// One layer's part: each appending table's suffix, each rewritten table's")
    add("// changed and added entries, and every scalar, in pieces of at most")
    add("// %d fields." % CHUNK)
    add("public struct FrontPart {")
    for n in range(len(chunks)):
        add("    p%d: FrontPart%d" % (n, n))
    add("}")
    add("")
    add("extension FrontPart: NoCopy {}")
    add("")
    add("@synthesize")
    add("extension FrontPart: Serialize {}")
    add("@synthesize")
    add("extension FrontPart: Deserialize {}")
    add("")
    add("// The part of the layer whose appending tables run from `lo` to `hi` in")
    add("// `c`, the state at the end of drops, and whose rewritten tables and")
    add("// scalars stood at `before` when it began and at `after` when it ended.")
    add("public func front_part_make(c: &FrontCut, lo: &Vector<Int>, hi: &Vector<Int>, before: &FrontSnap,")
    add("                            after: &FrontSnap) -> FrontPart {")
    made = []
    for n, chunk in enumerate(chunks):
        snaps = ", &before.s%d, &after.s%d" % (n, n) if chunk_snaps(chunk) else ""
        made.append("p%d: front_make_%d(&c, &lo, &hi%s)" % (n, n, snaps))
    add("    FrontPart(" + ",\n              ".join(made) + ")")
    add("}")
    add("")
    add("// The first appending table of `c` that holds fewer than `hi` entries, or")
    add("// \"\": one that does was cut back after the layer `hi` ends, which only a")
    add("// rewritten table may be.")
    add("public func front_part_shrunk(c: &FrontCut, hi: &Vector<Int>) -> String {")
    for n in range(len(chunks)):
        add("    let s%d = front_shrunk_%d(&c, &hi)" % (n, n))
        add("    if s%d.len() > 0 {" % n)
        add("        return s%d" % n)
        add("    }")
    add("    \"\"")
    add("}")
    add("")
    add("// `part` applied to `c`, the state before its layer: `c` then holds the")
    add("// state after it.")
    add("public func front_part_apply(c: &var FrontCut, part: &FrontPart) {")
    for n in range(len(chunks)):
        add("    front_apply_%d(&var c, &part.p%d)" % (n, n))
    add("}")
    add("")
    compared = sorted({t for _, t, r in tables if r and compares(t)})
    for t in compared:
        same = {"String": "after[i].equals(before[i])"}.get(t, "after[i] == before[i]")
        if t in BACKINGS:
            same = "(after[i] as %s) == (before[i] as %s)" % (BACKINGS[t], BACKINGS[t])
        add("// What a layer did to a table of `%s` that stood at `before` and ends at" % t)
        add("// `after`: every entry that differs below the shorter length, then every")
        add("// entry past `before`'s.")
        add("func front_rewrite_%s(before: &Vector<%s>," % (t, spell(t)))
        add("    after: &Vector<%s>) -> FrontRewrite<%s> {" % (spell(t), spell(t)))
        add("    var at = Vector<Int>()")
        add("    var values = Vector<%s>()" % spell(t))
        add("    let common = if before.len() < after.len() { before.len() } else { after.len() }")
        add("    var i = 0")
        add("    while i < common {")
        add("        if not (%s) {" % same)
        add("            try! at.push(i)")
        add("            try! values.push(after[i])")
        add("        }")
        add("        i = i + 1")
        add("    }")
        add("    while i < after.len() {")
        add("        try! at.push(i)")
        add("        try! values.push(after[i])")
        add("        i = i + 1")
        add("    }")
        add("    FrontRewrite<%s>(length: after.len(), at: move at, values: move values)" % spell(t))
        add("}")
        add("")
    lines = ["// GENERATED by compiler/tools/front_parts.py from the front-end stages' struct",
             "// declarations: do not edit; run the tool and review the diff (SL-955 unit 4b).",
             "",
             "import sawmono.frontimage.{FrontCut}",
             "import sawmono.frontrewrite.{FrontRewrite, front_append, front_copy, front_rewrite_apply, front_rewrite_whole,",
             "                             front_suffix}"]
    for n, mod in sorted(used.items()):
        if n != "FrontCut":
            lines.append("import %s.{%s as T_%s}" % (mod, n, n))
    lines.append("")
    return "\n".join(lines + body) + "\n"


def table_count():
    """How many tables the slicer cuts."""
    structs, _ = load()
    tables, scalars = [], []
    walk(structs, "FrontCut", [], tables, scalars, None)
    return len(tables)


def check():
    """A failure line, or None when the committed slicer is current."""
    want = render()
    try:
        with open(OUT, encoding="utf-8") as fh:
            have = fh.read()
    except OSError:
        have = None
    if have != want:
        return "%s is stale; run compiler/tools/front_parts.py and review the diff" % os.path.relpath(OUT, REPO)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail when the file is stale")
    ap.add_argument("--unmarked", metavar="TYPE.FIELD",
                    help="write the slicer as though this field's marker were missing (the fault pin's)")
    ap.add_argument("--out", metavar="PATH", help="write here instead; required with --unmarked")
    args = ap.parse_args(argv)
    if args.check:
        problem = check()
        print(problem or "front parts: current")
        return 1 if problem else 0
    if args.unmarked and not args.out:
        ap.error("--unmarked writes a faulty slicer, which never replaces the committed one: name --out")
    out = args.out or OUT
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(args.unmarked))
    print("front parts: wrote %s" % os.path.relpath(out, REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
