#!/usr/bin/env python3
"""Write the parser's grammar tables, `compiler/parse/src/grammar.saw`, from GRAMMAR.md.

    python compiler/tools/grammar_tables.py           rewrite the file
    python compiler/tools/grammar_tables.py --check   fail when it is stale

The tables are the one mapping from the grammar to the parser's tree: every
alternative as an `Alt` case with its stable name and the node Kind it builds,
and every refusal a parser names as a `Rule` case. They come from the same model
of GRAMMAR.md the recognizer reads (`compiler/tests/grammar/extract.py`), so a
grammar change is a regeneration, and `compiler/tests/run.py` fails while the
committed file differs from what this writes.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "compiler", "tests", "grammar"))

import extract  # noqa: E402

OUT = os.path.join(REPO, "compiler", "parse", "src", "grammar.saw")
# The production whose layers the dump spells as one Kind whatever token wrote
# them (compiler/tests/parse/README.md, Optional types).
OPTIONAL_TYPE_PRODUCTION = "syntax.type.suffix"
OPTIONAL_TYPE = "OptionalType"


def case_name(name):
    """`syntax.decl.import-target.module-alias` -> `Decl_ImportTarget_ModuleAlias`."""
    segments = name.split(".")[1:]
    return "_".join("".join(w.capitalize() for w in s.split("-")) for s in segments)


def alternatives(model):
    """[(case, name, kind)] for every alternative, in document order."""
    out = []
    for p in model.productions:
        for a in p.alternatives:
            if p.node == "-":
                kind = ""
            elif p.name == OPTIONAL_TYPE_PRODUCTION:
                kind = OPTIONAL_TYPE
            elif len(p.alternatives) > 1:
                kind = p.node + "." + a.effective_name.rsplit(".", 1)[1]
            else:
                kind = p.node
            out.append((case_name(a.effective_name), a.effective_name, kind))
    return out


def rules(model):
    """[(case, name)]: the section-13 rules, the lexical rules and the removed
    productions, which are every name a refusal can carry."""
    names = list(model.rule_ids()) + list(model.lexical_rule_ids())
    names += [p.name for p in model.productions if p.status == "removed"]
    return [(case_name(n), n) for n in names]


def unique(pairs, what):
    seen = {}
    for case, name in pairs:
        if case in seen:
            raise SystemExit("grammar_tables: %s %s and %s share the case name %s"
                             % (what, seen[case], name, case))
        seen[case] = name


def render(model):
    alts = alternatives(model)
    refusals = rules(model)
    unique([(c, n) for c, n, _ in alts], "alternatives")
    unique(refusals, "rules")
    lines = [
        "// The parser's grammar tables, written from GRAMMAR.md by",
        "// compiler/tools/grammar_tables.py: edit the grammar and regenerate this file.",
        "",
        "// Every alternative of GRAMMAR.md, in document order.",
        "public enum Alt: UInt16 {",
    ]
    for k, (case, _, _) in enumerate(alts):
        lines.append("    case %s = %d%s" % (case, k, "," if k + 1 < len(alts) else ""))
    lines += ["}", "", "public static ALT_COUNT: Int = %d" % len(alts), ""]
    lines += ["// The alternative's stable name.",
              "public func alt_name(alt: Alt) -> String {", "    match alt {"]
    for k, (case, name, _) in enumerate(alts):
        lines.append('        case %s -> "%s"%s' % (case, name, "," if k + 1 < len(alts) else ""))
    lines += ["    }", "}", ""]
    lines += ["// The Kind of the node the alternative builds, suffixed as GRAMMAR.md section 1",
              "// says, or the empty string for a production that builds none.",
              "public func alt_kind(alt: Alt) -> String {", "    match alt {"]
    for k, (case, _, kind) in enumerate(alts):
        lines.append('        case %s -> "%s"%s' % (case, kind, "," if k + 1 < len(alts) else ""))
    lines += ["    }", "}", ""]
    kinds = []
    for case, _, kind in alts:
        if kind and kind not in [k for k, _ in kinds]:
            kinds.append((kind, case))
    lines += ["// The first alternative that builds a node of this Kind, or None for a Kind",
              "// no alternative builds.",
              "public func alt_for_kind(kind: String) -> Alt? {", "    match kind {"]
    for kind, case in kinds:
        lines.append('        case "%s" -> Alt.%s,' % (kind, case))
    lines += ["        case _ -> None", "    }", "}", ""]
    lines += ["// Every name a refusal carries: a section-13 rule, a lexical rule or a",
              "// removed production.",
              "public enum Rule: UInt16 {"]
    for k, (case, _) in enumerate(refusals):
        lines.append("    case %s = %d%s" % (case, k, "," if k + 1 < len(refusals) else ""))
    lines += ["}", "", "public func rule_name(rule: Rule) -> String {", "    match rule {"]
    for k, (case, name) in enumerate(refusals):
        lines.append('        case %s -> "%s"%s' % (case, name, "," if k + 1 < len(refusals) else ""))
    lines += ["    }", "}", ""]
    return "\n".join(lines)


def check():
    """A failure line, or None when the committed tables are current."""
    want = render(extract.extract())
    try:
        with open(OUT, encoding="utf-8") as fh:
            have = fh.read()
    except OSError:
        have = None
    if have != want:
        return ("%s is stale; run compiler/tools/grammar_tables.py and review the diff"
                % os.path.relpath(OUT, REPO))
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail when the file is stale")
    args = ap.parse_args(argv)
    if args.check:
        problem = check()
        print(problem or "grammar tables: current")
        return 1 if problem else 0
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(render(extract.extract()))
    print("grammar tables: wrote %s" % os.path.relpath(OUT, REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
