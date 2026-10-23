#!/usr/bin/env python3
"""The source rules over the compiler's own source and the new std.

Each rule in `RULES` names its source in its diagnostic. sawc2 reads every
file (`sawc2_reading.py`): `sawc2 lex` gives the tokens and `sawc2 parse
--dump` the tree, so GRAMMAR.md decides what parses and a file sawc2 refuses
is refused as `grammar`. The two profiles differ only in what a file may
import. The workaround inventory prints first over the compiler's tree.

    python compiler/tools/subset_check.py          # compiler/**/*.saw, no tests/
    python compiler/tools/subset_check.py FILE...  # these files, the compiler profile
    python compiler/tools/subset_check.py --std [FILE...]  # the std profile over std/
"""
import dataclasses
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sawc2_reading  # noqa: E402
import ast_nodes as A  # noqa: E402  (on sys.path through sawc2_reading)
from build import STAGE_PACKAGES  # noqa: E402

RULES = {
    "grammar": "GRAMMAR.md: sawc2's parser must accept the source",
    "import-allowlist": "LANGUAGE_SPEC, Package Structure; SL:hazards S27",
    "workaround-marker": "SL:hazards: a workaround names the entry it works around",
    "redundant-visibility": "LANGUAGE_SPEC: a field's tier is stated once, on the type",
}

VISIBILITY_SPELLING = {
    A.Visibility.PUBLIC: "public",
    A.Visibility.PACKAGE: "public(package)",
    A.Visibility.PARENT: "public(parent)",
}

# The tracked copy of SL:hazards, whose headings name its entries. Its sibling
# `hazards.json` holds the page's history and threads, not the entries.
HAZARDS_DOC = os.path.join(REPO, ".sawtracker", "docs", "hazards.md")
_HAZARD_HEADING_RE = re.compile(r"^### ([SL]\d+)\. ", re.M)
# Anything that reads as a workaround marker, however it is spelled, and the one
# spelling a marker may take: the entry, then the code the workaround replaces,
# then optionally ` — ` and why.
_MARKER_LIKE_RE = re.compile(r"//.*stage[\s_-]*0[\s_-]*work[\s_-]*around", re.I)
_MARKER_RE = re.compile(
    r"// Stage 0 workaround \(SL:hazards ([SL]\d+)\): canonical: (\S.*?)(?: — \S.*)?\s*$")
MARKER_FORM = "// Stage 0 workaround (SL:hazards ID): canonical: <the code it replaces>"

PACKAGE_RELATIVE_HEADS = ("parent", "package")

STD_ROOT = os.path.join(REPO, "std")


@dataclasses.dataclass(frozen=True, order=True)
class Diagnostic:
    path: str
    line: int
    rule: str
    message: str

    def render(self):
        return "%s:%d: %s: %s (%s)" % (self.path, self.line, self.rule, self.message,
                                       RULES[self.rule])


class SourceFile:
    """One file as sawc2 reads it: its text, tokens and tree in the frozen
    parser's shapes, or `grammar_error`, sawc2's refusal as (line, message)."""

    def __init__(self, path, reading):
        self.path = path
        self.rel = os.path.relpath(path, REPO)
        with open(path, encoding="utf-8") as fh:
            self.text = fh.read()
        self.tokens = reading.tokens
        self.program = reading.program
        self.grammar_error = reading.error


def read_sources(paths):
    """{path: SourceFile} for `paths`, every file parsed by one sawc2 process."""
    readings = sawc2_reading.read_files(list(paths))
    return {p: SourceFile(p, readings[p]) for p in paths}


def programs(prog):
    """`prog` and every inline `module m { ... }` body inside it, outermost first."""
    stack = [prog]
    while stack:
        p = stack.pop()
        yield p
        for md in reversed(p.module_decls):
            if md.body is not None:
                stack.append(md.body)


def children(node):
    """The structural child nodes of `node`, in field order."""
    out = []
    for f in A.structural_fields(node):
        _collect(getattr(node, f.name), out)
    return out


def _collect(value, out):
    if isinstance(value, A.SawType) or value is None:
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _collect(v, out)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        out.append(value)


def walk(node):
    """`node` and every structural descendant, depth first."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(children(n)))


_HAZARD_IDS = None


def hazard_ids():
    """The S and L entries SL:hazards declares, read from its tracked copy."""
    global _HAZARD_IDS
    if _HAZARD_IDS is None:
        with open(HAZARDS_DOC, encoding="utf-8") as fh:
            _HAZARD_IDS = frozenset(_HAZARD_HEADING_RE.findall(fh.read()))
        if not _HAZARD_IDS:
            raise RuntimeError("subset_check: %s names no S or L entry"
                               % os.path.relpath(HAZARDS_DOC, REPO))
    return _HAZARD_IDS


def workaround_markers(text):
    """Each line of `text` that reads as a Stage 0 workaround marker, as
    (line, hazard id, canonical code), the last two None when the marker is not
    in `MARKER_FORM`."""
    out = []
    for lineno, line in enumerate(text.split("\n"), 1):
        like = _MARKER_LIKE_RE.search(line)
        if like:
            exact = _MARKER_RE.match(line, like.start())
            out.append((lineno,) + (exact.groups() if exact else (None, None)))
    return out


def workaround_inventory(paths):
    """The well-formed markers in `paths`, rendered: a count per hazard entry,
    then each marker's entry, `file:line` and canonical code."""
    found = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            for line, hazard, canonical in workaround_markers(fh.read()):
                if hazard is not None:
                    found.append((hazard, os.path.relpath(path, REPO), line, canonical))
    counts = {}
    for hazard, _, _, _ in found:
        counts[hazard] = counts.get(hazard, 0) + 1
    order = sorted(counts, key=lambda h: (h[0], int(h[1:])))
    out = ["stage 0 workarounds: %d marker(s)%s" % (
        len(found), "".join("; %s: %d" % (h, counts[h]) for h in order))]
    for hazard, rel, line, canonical in sorted(found, key=lambda f: (f[1], f[2])):
        out.append("  %s %s:%d: canonical: %s" % (hazard, rel, line, canonical))
    return out


class FileChecker:
    def __init__(self, src, std_profile=False):
        self.src = src
        self.std_profile = std_profile
        self.diags = []

    def report(self, line, rule, message):
        d = Diagnostic(self.src.rel, line, rule, message)
        if d not in self.diags:
            self.diags.append(d)

    def run(self):
        self.check_workaround_markers()
        if self.src.grammar_error:
            self.report(self.src.grammar_error[0], "grammar", self.src.grammar_error[1])
            return self.diags
        for prog in programs(self.src.program):
            for imp in prog.imports:
                self.check_import(imp)
            for s in prog.structs:
                self.check_field_visibility(s)
        return self.diags

    def check_workaround_markers(self):
        """A marker is how a Stage 0 workaround is found again, so one that is
        misspelled or names no entry is lost."""
        for line, hazard, _ in workaround_markers(self.src.text):
            if hazard is None:
                self.report(line, "workaround-marker",
                            "write a workaround marker exactly as `%s`" % MARKER_FORM)
            elif hazard not in hazard_ids():
                self.report(line, "workaround-marker",
                            "`%s` is not an entry of SL:hazards" % hazard)

    def check_field_visibility(self, s):
        """A field inherits its struct's tier, so writing that same tier on it
        says nothing; only a narrowing, `private`, is written."""
        tier = VISIBILITY_SPELLING.get(s.visibility)
        if tier is None:
            return
        for f in s.fields:
            if f.visibility_written and f.visibility == s.visibility:
                self.report(f.line, "redundant-visibility",
                            "`%s` repeats the tier of `%s struct %s`; write the field "
                            "bare, and mark only a narrowing `private`" % (tier, tier, s.name))

    def check_import(self, imp):
        path = imp.path
        head = path[0] if path else ""
        if self.std_profile:
            if head != "std" or not os.path.isfile(os.path.join(STD_ROOT, *path[1:]) + ".saw"):
                self.report(imp.line, "import-allowlist",
                            "the new std imports only its own modules, and `%s` is not one"
                            % ".".join(path))
        elif head == "src":
            # A package's module root is its `src/` (LANGUAGE_SPEC, Package
            # Structure), so `src` names no module path segment.
            self.report(imp.line, "import-allowlist",
                        "`src` heads no module path: a package's module root is its `src/`; "
                        "name the stage, `import <stage>.%s`" % ".".join(path[1:]))
        elif head != "std" and head not in PACKAGE_RELATIVE_HEADS and \
                head not in [name for name, _ in STAGE_PACKAGES]:
            # Any other bare import is searched from the entry file, where one
            # file reached by two spellings is two modules (SL:hazards S27). The
            # fix of that retires this refusal (SL-826).
            self.report(imp.line, "import-allowlist",
                        "`%s` is neither std, a compiler stage, nor package-relative" % head)


def check_files(paths, std_profile=False):
    """The rules over `paths`, each file on its own."""
    paths = sorted(set(paths))
    sources = read_sources(paths)
    diags = []
    for p in paths:
        diags.extend(FileChecker(sources[p], std_profile).run())
    return sorted(set(diags))


def tree_files():
    """Every compiler source file in scope, sorted: `compiler/tests/` holds
    fixtures of arbitrary Saw, so it is left out."""
    root = os.path.join(REPO, "compiler")
    out = []
    for path in glob.glob(os.path.join(root, "**", "*.saw"), recursive=True):
        if os.path.relpath(path, root).split(os.sep)[0] != "tests":
            out.append(path)
    return sorted(out)


def std_tree_files():
    """Every module of the new std, sorted."""
    return sorted(glob.glob(os.path.join(STD_ROOT, "**", "*.saw"), recursive=True))


def check_std(paths=None):
    """The std profile over `paths`, by default every module of the new std."""
    return check_files(std_tree_files() if paths is None else paths, std_profile=True)


def check_tree():
    files = tree_files()
    return files, check_files(files)


STD_FLAG = "--std"


def main(argv):
    if argv[:1] == [STD_FLAG]:
        paths = [os.path.abspath(p) for p in argv[1:]] or std_tree_files()
        diags = check_std(paths)
        count = len(paths)
    elif argv:
        paths = [os.path.abspath(p) for p in argv]
        diags = check_files(paths)
        count = len(paths)
    else:
        files, diags = check_tree()
        count = len(files)
        for line in workaround_inventory(files):
            print(line)
    for d in diags:
        print(d.render())
    print("subset: %d file(s), %d diagnostic(s)" % (count, len(diags)))
    return 1 if diags else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
