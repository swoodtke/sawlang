#!/usr/bin/env python3
"""The generated negative cases: removed forms, section-12 N cells and P cells'
bare forms, mutations.

    python compiler/tests/grammar/negative.py            write them to compiler/tests/parse/negative/
    python compiler/tests/grammar/negative.py --check    fail when regenerating differs

Four case files of compiler/tests/parse/negative/ are generated, with their
expectations (cases.py): `removed`, a case per removed alternative, refused as
its removed production; `cells`, a case per section-12 N cell; `bare`, a case
per P cell, its generated program without the parentheses; and `mutations`,
one token dropped, duplicated or swapped, or a closing bracket dropped, in
each generated `/alt` case, a mutation the recognizer accepts discarded.
compiler/tests/parse/README.md describes each.

ENTRY POINTS
    generate
    check
"""
import argparse
import json
import os
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cases  # noqa: E402
import extract  # noqa: E402
import generate  # noqa: E402
import lexdump  # noqa: E402
import recognize  # noqa: E402

NEGATIVE = cases.NEGATIVE
REGENERATE = "compiler/tests/grammar/negative.py"
# Programs a cell is placed in after its context's first one, when that one's
# refusal is not named once: in an `if` head a trailing closure is refused by
# head-restriction and, read as the body, the brace after it by
# trailing-closure, while a `guard` head has one reading.
MORE_CONTEXTS = {
    "cond": [generate.in_function("guard " + generate.HOLE + " else {\n    return\n}")],
    "subj": [generate.in_function("guard let x = " + generate.HOLE + " else {\n    return\n}")],
}
MUTATIONS = ("drop", "dup", "swap", "close")
CLOSERS = (")", "]", "}")
# The generated positives the mutations start from: one per alternative.
MUTATED_VARIANT = "/alt"


def removed_alternatives(g):
    """[(nonterminal, rule index, the removed production it is refused as)] in
    grammar order: each alternative of a removed production, and each other
    alternative that names a removed production where it cannot be absent."""
    out = []
    for p in g.model.productions:
        if p.nonterminal is None:
            continue
        for ai in range(len(p.alternatives)):
            if p.status == "removed":
                out.append((p.nonterminal, ai, p.nonterminal))
                continue
            if generate.generated_alternative(g, p.nonterminal, ai):
                continue
            named = [s for s in p.alternatives[ai].items
                     if extract.NONTERMINAL_RE.match(s) and g.info[s].status == "removed"]
            if named:
                out.append((p.nonterminal, ai, named[0]))
    return out


class RemovedGenerator(generate.Generator):
    """The generator over a grammar that enables one removed production. A
    program is valid when that grammar accepts it and the default grammar
    refuses it as exactly that production (cases.Expectations.refusal)."""

    def __init__(self, exp, nonterminal):
        generate.Generator.__init__(self, recognize.Grammar(exp.model, {nonterminal}))
        self.exp = exp
        self.want = exp.g.info[nonterminal].name

    def valid(self, text):
        if text not in self.validated:
            ok = self.checked(text).verdict == "OK"
            if ok:
                try:
                    got = self.exp.refusal(text, "source-file")
                except cases.Problem:
                    got = None
                ok = got is not None and got[0] == self.want
            self.validated[text] = ok
        return self.validated[text]

    def alternative_program(self, nt, ai, repair=True):
        items = self.items(nt, ai)
        cheapest = {it.index: values[0][1] for it, _, values in self.options(items)}
        core = [cheapest.get(it.index) or self.tree(it.symbol) for it in items]
        return self.build(nt, core, set(), (nt, ai, ()), repair)


class Worker:
    def __init__(self):
        self.exp = cases.Expectations()
        self.generators = {}
        self.areas = {}
        self.waived = {item for kind, item in generate.load_waivers()[0] if kind == "removed"}

    def generator(self, nonterminal):
        if nonterminal not in self.generators:
            self.generators[nonterminal] = RemovedGenerator(self.exp, nonterminal)
        return self.generators[nonterminal]

    def expect(self, name, text):
        """The cases.evaluate list for a negative case of this text."""
        case = cases.Case(name, "source-file", text, cases.HEADER + name)
        try:
            lines, refusal, alts = self.exp.negative(case)
            return [name, text, lines, None, refusal, alts]
        except cases.Problem as e:
            return [name, text, None, str(e), None, []]

    def removed(self, nt, ai, enabled):
        name = self.exp.g.alternative(nt, int(ai)).effective_name
        # A waived alternative gets only its cheapest program: enough to show
        # that its waiver is no longer needed, without searching repairs that
        # the waiver says cannot succeed.
        text = self.generator(enabled).alternative_program(nt, int(ai), name not in self.waived)
        if text is None:
            return [[name, None, None, "no program is refused as %s alone"
                     % self.exp.g.info[enabled].name, None, []]]
        return [self.expect(name, text)]

    def cell(self, construct, ctx):
        """The construct in the first program of its context whose expectation
        the recognizer gives: one that refuses it by a single name, or reads
        its tokens as another construct."""
        name = "%s%s%s" % (construct, cases.CELL, ctx)
        result = None
        for template in generate.CONTEXTS[ctx][:1] + MORE_CONTEXTS.get(ctx, []):
            text = generate.splice(template, generate.INSTANCES[construct][0])
            result = self.expect(name, text)
            if result[3] is not None and result[3].startswith("accepted; "):
                result = self.expect(name, cases.PARSES_AS_NOTE + "\n" + text)
            if result[3] is None:
                break
        return [result]

    def generated(self, area):
        """The generated cases of one area, as (name, text) in file order."""
        if area not in self.areas:
            path = os.path.join(generate.GENERATED, area + ".saw")
            self.areas[area] = generate.read_cases(path) if os.path.exists(path) else []
        return self.areas[area]

    def bare(self, construct, ctx):
        """A P cell's construct without its parentheses, in the program its
        generated case stands in: refused, or read as another construct whose
        tree does not place it in the context."""
        name = "%s%s%s" % (construct, cases.BARE, ctx)
        area = generate.area_of(self.exp.model, construct)
        positive = dict(self.generated(area)).get("%s%s%s" % (construct, cases.CELL, ctx))
        instance = generate.INSTANCES[construct][0]
        if positive is None:
            return [[name, None, None, "the P cell has no generated case", None, []]]
        for template in generate.CONTEXTS[ctx]:
            if generate.splice(template, "(%s)" % instance) == positive:
                break
        else:
            return [[name, None, None, "no context program writes the generated case", None, []]]
        text = generate.splice(template, instance)
        result = self.expect(name, text)
        if result[3] is not None and result[3].startswith("accepted; "):
            result = self.expect(name, cases.PARSES_AS_NOTE + "\n" + text)
        return [result]

    def mutate(self, area, index):
        source, text = self.generated(area)[int(index)]
        out = []
        for kind in MUTATIONS:
            name = "%s/%s" % (source, kind)
            try:
                mutated, where = mutation(text, kind, name)
            except Discard as e:
                out.append([name, None, None, "discarded: %s" % e, None, []])
                continue
            result = self.expect("%s:%d" % (name, where), mutated)
            if result[3] is not None:
                result = [result[0], None, None, "discarded: " + result[3], None, []]
            out.append(result)
        return out

    def run(self, job):
        fields = job.split("\t")
        return getattr(self, fields[0])(*fields[1:])


def spelled(text, starts, toks):
    """[(start offset, spelling)] of each token but EOF."""
    out = []
    for n, t in enumerate(toks):
        if t.kind == "EOF":
            continue
        at = starts[t.line - 1] + t.column - 1
        if t.kind in ("INT", "FLOAT", "STRING", "INTERP_STRING"):
            text_of = lexdump.raw_spelling(text, starts, t, toks[n + 1] if n + 1 < len(toks) else None)
        elif t.kind == "HASH_DIRECTIVE":
            text_of = "#" + t.value
        else:
            text_of = t.value
        out.append((at, text_of))
    return out


class Discard(Exception):
    """A mutation that is not recorded, and why."""


def mutation(text, kind, name):
    """(mutated text, 1-based index of the token mutated) for one mutation of
    `text`, the position a stable hash of `name`. The text loses the
    whitespace a mutation leaves at a line's end and ends in exactly one line
    break. Discard when the text has no token the mutation applies to, or the
    lexer does not read the mutated text back as the mutated tokens."""
    toks, _ = lexdump.lex_text(text)
    spans = spelled(text, lexdump.line_starts(text), toks)
    # The text's final line break stays: every case ends in one.
    if spans and spans[-1][1] == "\n":
        spans = spans[:-1]
    if kind == "close":
        eligible = [k for k, (_, s) in enumerate(spans) if s in CLOSERS]
    elif kind == "swap":
        eligible = [k for k in range(len(spans) - 1) if spans[k][1] != spans[k + 1][1]]
    else:
        eligible = list(range(len(spans)))
    if not eligible:
        raise Discard("no token to %s" % kind)
    k = eligible[zlib.crc32(name.encode("utf-8")) % len(eligible)]
    at, tok = spans[k]
    end = at + len(tok)
    # A space where a token was, or around one moved, keeps its neighbours
    # from joining: `a.b` less its `.` is `a b`, not `ab`.
    if kind in ("drop", "close"):
        mutated = text[:at] + " " + text[end:]
        want = [s for n, (_, s) in enumerate(spans) if n != k]
    elif kind == "dup":
        mutated = text[:end] + ("" if tok == "\n" else " ") + tok + text[end:]
        want = [s for n, (_, s) in enumerate(spans) for _ in range(2 if n == k else 1)]
    else:
        nat, nxt = spans[k + 1]
        mutated = (text[:at] + " " + nxt + " " + text[end:nat] + " " + tok + " "
                   + text[nat + len(nxt):])
        want = [s for _, s in spans]
        want[k], want[k + 1] = want[k + 1], want[k]
    mutated = "\n".join(line.rstrip() for line in mutated.split("\n")).rstrip("\n") + "\n"
    try:
        got_toks, _ = lexdump.lex_text(mutated)
    except lexdump.LexError as e:
        raise Discard("the lexer refuses it: %s" % e)
    got = [s for _, s in spelled(mutated, lexdump.line_starts(mutated), got_toks)]
    if got[-1:] == ["\n"]:
        got = got[:-1]
    if got != want:
        raise Discard("the lexer reads other tokens")
    return mutated, k + 1


def jobs(g):
    """The generation jobs in file order: removed forms, N cells, P cells' bare
    forms, mutations."""
    out = ["removed\t%s\t%d\t%s" % r for r in removed_alternatives(g)]
    table = g.model.tables_of(extract.MATRIX)[0]
    contexts = table.header[1:]
    for code, kind in (("N", "cell"), ("P", "bare")):
        for _, row in table.rows:
            for ctx, cell in zip(contexts, row[1:]):
                if cell == code:
                    out.append("%s\t%s\t%s" % (kind, row[0], ctx))
    for _, area in sorted(generate.AREAS.items()):
        path = os.path.join(generate.GENERATED, area + ".saw")
        if not os.path.exists(path):
            continue
        for k, (name, _) in enumerate(generate.read_cases(path)):
            if name.endswith(MUTATED_VARIANT):
                out.append("mutate\t%s\t%d" % (area, k))
    return out


def run_worker():
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    worker = Worker()
    for line in sys.stdin:
        sys.stdout.write(json.dumps(worker.run(line.rstrip("\n"))) + "\n")
    return 0


def generate_all(jobs_count=None):
    """{file stem: [[name, text, lines, problem, refusal, alternatives]]}."""
    g = recognize.Grammar(extract.extract())
    todo = jobs(g)
    results = recognize.run_workers([os.path.abspath(__file__), "--worker"], todo,
                                    jobs_count or recognize.default_jobs())
    out = {"removed": [], "cells": [], "bare": [], "mutations": []}
    stems = {"removed": "removed", "cell": "cells", "bare": "bare", "mutate": "mutations"}
    seen = set()
    for job, result in zip(todo, results):
        stem = stems[job.split("\t")[0]]
        for r in result:
            # Two positives can mutate into one program; it is recorded once.
            if stem == "mutations" and r[1] is not None:
                if r[1] in seen:
                    r = [r[0], None, None, "discarded: a duplicate", None, []]
                seen.add(r[1])
            out[stem].append(r)
    return out


def files_of(generated):
    """{file name: text} for the case files and their expectations."""
    out = {}
    for stem, results in sorted(generated.items()):
        kept = [r for r in results if r[2] is not None]
        header = [cases.HEADER + r[0] for r in kept]
        out[stem + ".saw"] = "\n".join(h + "\n" + r[1] for h, r in zip(header, kept))
        out[stem + ".expect"] = "\n".join(h + "\n" + "\n".join(r[2]) + "\n"
                                          for h, r in zip(header, kept))
    return out


def problems(generated, waivers):
    """Failure lines: a removed form, an N cell or a P cell with no case,
    unless waived."""
    out = []
    for stem, kind in (("removed", "removed"), ("cells", "n-cell"), ("bare", "p-cell")):
        for r in generated[stem]:
            if r[2] is None:
                item = r[0] if kind == "removed" else " ".join(cases.cell_of(r[0]))
                if (kind, item) not in waivers:
                    out.append("negative case %s: %s" % (r[0], r[3]))
    return out


def counts_of(generated):
    mutations = generated["mutations"]
    return {"negative removed-form cases": sum(1 for r in generated["removed"] if r[2]),
            "negative cell cases": sum(1 for r in generated["cells"] if r[2]),
            "negative bare-form cases": sum(1 for r in generated["bare"] if r[2]),
            "negative mutations": sum(1 for r in mutations if r[2]),
            "discarded mutations": sum(1 for r in mutations if r[2] is None)}


def compare(files):
    """Failure lines where negative/'s generated files differ from `files`."""
    out = []
    for name in sorted(files):
        path = os.path.join(NEGATIVE, name)
        rel = os.path.relpath(path, extract.REPO)
        if not os.path.exists(path):
            out.append("%s: missing; run %s" % (rel, REGENERATE))
            continue
        with open(path, encoding="utf-8") as fh:
            have = fh.read()
        if have != files[name]:
            out.append("%s: regenerating it differs at %s; run %s and review the diff"
                       % (rel, cases.first_difference(have, files[name]), REGENERATE))
    return out


def check(jobs_count=None, waivers=None):
    """(failure lines, counts, generated): regenerating reproduces negative/'s
    generated files, and every removed form and N cell has its case."""
    generated = generate_all(jobs_count)
    if waivers is None:
        waivers = generate.load_waivers()[0]
    failures = problems(generated, waivers) + compare(files_of(generated))
    return failures, counts_of(generated), generated


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="compare with the committed files")
    ap.add_argument("--jobs", type=int, default=recognize.default_jobs())
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    if args.worker:
        return run_worker()
    if args.check:
        failures, counts, _ = check(args.jobs)
        for f in failures:
            print(f)
        summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
        print("negative corpus: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                           summary))
        return 1 if failures else 0
    generated = generate_all(args.jobs)
    failures = problems(generated, generate.load_waivers()[0])
    for f in failures:
        print(f)
    if failures:
        print("negative corpus: nothing written: %d problem(s)" % len(failures))
        return 1
    files = files_of(generated)
    os.makedirs(NEGATIVE, exist_ok=True)
    for name, text in sorted(files.items()):
        with open(os.path.join(NEGATIVE, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts_of(generated).items()))
    print("negative corpus: wrote %d file(s): %s" % (len(files), summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
