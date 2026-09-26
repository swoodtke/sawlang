#!/usr/bin/env python3
"""The parser corpus generator: cases derived from GRAMMAR.md, with their dumps.

    python compiler/tests/grammar/generate.py            write compiler/tests/parse/generated/
    python compiler/tests/grammar/generate.py --check    fail when regenerating differs

For every non-removed alternative it writes a case, and one per value of each of
the alternative's options: an optional item present and absent, a repetition
written 0, 1 and many times, each choice of a group. It writes one case per
pair of options of one alternative set together, and one per allowed
section-12 cell, placing the construct in that context. Each case is a whole
program whose single tree the reference recognizer gives, whose tree uses the
alternative the case is named for with the option values it names (or records
the cell), and whose dump comes from dump.py; compiler/tests/parse/README.md
describes the files. A case for which no such program exists is a generator
bug, and generation fails unless waivers.tsv waives the case or its item.
`--check` also runs the `parsecoverage` check.

ENTRY POINTS
    generate
    check
"""
import argparse
import collections
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dump  # noqa: E402
import extract  # noqa: E402
import lexdump  # noqa: E402
import recognize  # noqa: E402
from recognize import is_nonterminal  # noqa: E402

PARSE_DIR = os.path.join(extract.REPO, "compiler", "tests", "parse")
GENERATED = os.path.join(PARSE_DIR, "generated")
HEADER = "// case: "
# A repetition's "many".
MANY = 3
# How deep a repair looks for a choice to change, below an item or a host frame,
# and how many host frames up it looks.
REPAIR_DEPTH = 4
REPAIR_FRAMES = 5
# A repair that changes two choices tries them among this many single changes,
# and a repair tries at most this many hosts.
PAIR_EDITS = 40
PAIR_CHAINS = 3
HOST_CHAINS = 40
# The recognizer results a generator keeps, for the programs it checked last:
# a result holds its charts, and each case needs only its own.
CHECKED_KEPT = 32
# The rule the cheapest expansion of a nonterminal takes, where the cheapest by
# length breaks a section-13 rule wherever it stands: a receiver is only a
# method's first parameter (syntax.rule.receiver-and-static).
PREFER = {"param": "syntax.decl.param.plain"}
# Parents a host avoids, by what standing in them adds to its cost; every
# production of the test area adds 100 (Generator._penalty).
HOST_PENALTY = {"destructure-stmt": 10.0, "static-init": 10.0, "static-assert": 10.0}
# The grammar areas, GRAMMAR.md sections 3 to 9, by section number: a case goes
# to the file of the section its production is written in.
AREAS = {"3": "declarations", "4": "attributes", "5": "types", "6": "statements",
         "7": "expressions", "8": "patterns", "9": "borrow"}

# An identifier's placeholder until a case is formatted, which names each one
# afresh: a selective import must not bind a name twice
# (syntax.rule.import-names).
IDENT = "\x00ident"
# How a token-kind terminal is written in a case.
SPELLINGS = {
    "IDENT": IDENT, "INT": "1", "FLOAT": "1.5", "STRING": '"C"', "INTERP_STRING": '"{x}"',
    "DOLLAR_PARAM": "$0", "NON_BRACE": "x", "EOF": "", "NEWLINE": "\n",
}
# A token's cost when choosing the shortest expansion. An identifier is the
# cheapest operand, so a name rather than `1` or `..` stands for an expression.
COSTS = {"IDENT": 0.9, "INT": 1.05, "FLOAT": 1.1, "STRING": 1.1, "INTERP_STRING": 1.2,
         "DOLLAR_PARAM": 1.2, "NON_BRACE": 1.0, "EOF": 0.0, "NEWLINE": 1.0}
# The program each start symbol other than source-file is parsed in; HOLE is
# where the start symbol's text goes.
HOLE = "\x00hole"
START_HOSTS = {
    "interp-segment": ["func", IDENT, "(", ")", "{", "\n", '"{' + HOLE + '}"', "\n", "}"],
}


class Tree:
    """One expansion: a symbol, the rule it takes (None for a terminal or a
    fixed token run), and its kids."""
    __slots__ = ("sym", "rule", "kids", "fixed")

    def __init__(self, sym, rule=None, kids=(), fixed=None):
        self.sym = sym
        self.rule = rule
        self.kids = tuple(kids)
        self.fixed = fixed

    def tokens(self):
        if self.fixed is not None:
            return list(self.fixed)
        return [t for k in self.kids for t in k.tokens()]


class Item:
    """One top-level item of an alternative: its symbol in the recognizer's
    rules, and its text in GRAMMAR.md."""

    def __init__(self, index, symbol, text):
        self.index = index
        self.symbol = symbol
        self.text = text


def item_texts(items):
    """The texts of an alternative's top-level items, in order, `ε` dropped."""
    out = []
    k = 0
    while k < len(items):
        if items[k] == "ε":
            k += 1
            continue
        start = k
        if items[k] == "(":
            depth = 0
            while True:
                depth += {"(": 1, ")": -1}.get(items[k], 0)
                k += 1
                if depth == 0:
                    break
        else:
            k += 1
        if k < len(items) and items[k] in ("?", "*", "+"):
            k += 1
        text = " ".join(items[start:k])
        for a, b in (("( ", "("), (" )", ")"), (" ?", "?"), (" *", "*"), (" +", "+")):
            text = text.replace(a, b)
        out.append(text)
    return out


class Generator:
    def __init__(self, g, waived_cases=()):
        self.g = g
        self.model = g.model
        self.waived_cases = set(waived_cases)
        self.best = self._minimal()
        self.filled = self._minimal_nonempty()
        self.frames = self._frames("source-file")
        self.start_frames = {s: self._frames(s) for s in START_HOSTS}
        self.validated = {}
        self._checked = collections.OrderedDict()
        self._realized = {}
        self.intended = {}
        self._chains = {}

    # Expansions ---------------------------------------------------------------

    def _cost(self, sym):
        if sym[:1] in "\"'":
            return 1.0
        return COSTS.get(sym, 1.0)

    def _live(self, nt):
        return [ri for ri, rule in enumerate(self.g.prods[nt]) if recognize.NEVER not in rule]

    def _minimal(self):
        """{nonterminal: (cost, rule index)} for the cheapest expansion of each
        nonterminal the recognizer can derive."""
        best = {}
        changed = True
        while changed:
            changed = False
            for nt in sorted(self.g.prods):
                for ri in self._live(nt):
                    total = 0.0
                    for sym in self.g.prods[nt][ri]:
                        if is_nonterminal(sym):
                            if sym not in best:
                                break
                            total += best[sym][0]
                        else:
                            total += self._cost(sym)
                    else:
                        if nt not in best or total < best[nt][0] - 1e-9:
                            best[nt] = (total, ri)
                            changed = True
        for nt, name in PREFER.items():
            ri = next(ri for ri in self._live(nt)
                      if self.g.alternative(nt, ri).effective_name == name)
            best[nt] = (best[nt][0], ri)
        return best

    def _written(self, sym):
        """Whether a terminal is written as a token: the end of input is not."""
        return self.spell(sym) != ""

    def _minimal_nonempty(self):
        """{nonterminal: (cost, rule index, position)} for the cheapest
        expansion of each nonterminal that writes a token: the rule, and the
        position whose symbol writes one."""
        filled = {}
        changed = True
        while changed:
            changed = False
            for nt in sorted(self.g.prods):
                for ri in self._live(nt):
                    rule = self.g.prods[nt][ri]
                    if any(is_nonterminal(s) and s not in self.best for s in rule):
                        continue
                    base = sum(self.best[s][0] if is_nonterminal(s) else self._cost(s) for s in rule)
                    for k, sym in enumerate(rule):
                        if is_nonterminal(sym):
                            if sym not in filled:
                                continue
                            total = base - self.best[sym][0] + filled[sym][0]
                        elif self._written(sym):
                            total = base
                        else:
                            continue
                        if nt not in filled or total < filled[nt][0] - 1e-9:
                            filled[nt] = (total, ri, k)
                            changed = True
        return filled

    def tree(self, sym, rule=None):
        """The cheapest expansion of sym, by rule `rule` when it is given."""
        if not is_nonterminal(sym):
            return Tree(sym, fixed=[self.spell(sym)])
        if sym.startswith(recognize.SHIFT_AUX):
            return Tree(sym, fixed=["<<" if sym.startswith("__shl") else ">>"])
        ri = self.best[sym][1] if rule is None else rule
        return Tree(sym, ri, [self.tree(s) for s in self.g.prods[sym][ri]])

    def filled_tree(self, sym, rule=None):
        """The cheapest expansion of sym, by rule `rule` when it is given, that
        writes at least one token, or None when there is none. Where the
        cheapest expansion writes one, it is that expansion."""
        if not is_nonterminal(sym):
            return Tree(sym, fixed=[self.spell(sym)]) if self._written(sym) else None
        if sym.startswith(recognize.SHIFT_AUX):
            return self.tree(sym)
        if (rule is not None or sym in self.best) and all(
                not is_nonterminal(s) or s in self.best
                for s in self.g.prods[sym][self.best[sym][1] if rule is None else rule]):
            cheapest = self.tree(sym, rule)
            if any(cheapest.tokens()):
                return cheapest
        if rule is None:
            if sym not in self.filled:
                return None
            _, rule, _ = self.filled[sym]
        options = []
        prods = self.g.prods[sym][rule]
        for k, s in enumerate(prods):
            if is_nonterminal(s) and (s not in self.filled or s not in self.best):
                continue
            if not is_nonterminal(s) and not self._written(s):
                continue
            cost = self.filled[s][0] - self.best[s][0] if is_nonterminal(s) else 0.0
            options.append((cost, k))
        if not options:
            return None
        _, k = min(options)
        return Tree(sym, rule, [self.filled_tree(s) if n == k else self.tree(s)
                                for n, s in enumerate(prods)])

    def spell(self, sym):
        if sym[:1] in "\"'":
            return sym[1:-1]
        return SPELLINGS.get(sym, IDENT)

    def neighbours(self, t, depth=REPAIR_DEPTH):
        """Expansions that differ from t in one choice at most `depth` levels
        down: another rule there, expanded at its cheapest. A repetition's
        choice is its count."""
        out = []
        if t.rule is None or depth == 0:
            return out
        for ri in self._live(t.sym):
            if ri != t.rule:
                out.extend(self._with_kid_choices(self.tree(t.sym, ri)))
        if t.sym.startswith("__rep") and self.g.prods[t.sym][1][:1] == (t.sym,):
            # A repetition written once more, so `x*` reaches two and more.
            out.extend(self._with_kid_choices(
                Tree(t.sym, 1, [t, self.tree(self.g.prods[t.sym][1][1])]), last=True))
        for k, kid in enumerate(t.kids):
            for n in self.neighbours(kid, depth - 1):
                kids = list(t.kids)
                kids[k] = n
                out.append(Tree(t.sym, t.rule, kids))
        return out

    def _with_kid_choices(self, t, last=False):
        """t, then t with one of its kids (only the last when `last`) expanded by
        each of the kid's other rules, so a new rule's own choice comes with it."""
        out = [t]
        positions = [len(t.kids) - 1] if last else range(len(t.kids))
        for k in positions:
            kid = t.kids[k]
            if kid.rule is None:
                continue
            for ri in self._live(kid.sym):
                if ri != kid.rule:
                    kids = list(t.kids)
                    kids[k] = self.tree(kid.sym, ri)
                    out.append(Tree(t.sym, t.rule, kids))
        return out

    def inner_edits(self, t):
        """Trees that keep t's own choice, the count of a repetition included, and
        change one choice inside it."""
        out = []
        for k, kid in enumerate(t.kids):
            subs = self.inner_edits(kid) if kid.sym == t.sym else self.neighbours(kid)
            for n in subs:
                kids = list(t.kids)
                kids[k] = n
                out.append(Tree(t.sym, t.rule, kids))
        return out

    # Hosts: where each nonterminal stands in a whole program -----------------

    def _frames(self, start):
        """{nonterminal: [(parent, rule index, position), ...]}: the cheapest
        chain of frames from the nonterminal up to `start`."""
        frames = {start: []}
        cost = {start: 0.0}
        changed = True
        while changed:
            changed = False
            for nt in sorted(self.g.prods):
                if nt not in frames:
                    continue
                for ri in self._live(nt):
                    rule = self.g.prods[nt][ri]
                    others = sum(self.best[s][0] if is_nonterminal(s) else self._cost(s)
                                 for s in rule if not (is_nonterminal(s) and s not in self.best))
                    for k, sym in enumerate(rule):
                        if not is_nonterminal(sym) or sym.startswith(recognize.SHIFT_AUX):
                            continue
                        own = self.best[sym][0] if sym in self.best else 0.0
                        c = cost[nt] + others - own + 0.001 * k + self._penalty(nt)
                        if sym not in cost or c < cost[sym] - 1e-9:
                            frames[sym] = [(nt, ri, k)] + frames[nt]
                            cost[sym] = c
                            changed = True
        return frames

    def _penalty(self, parent):
        """What standing in `parent` adds to a host's cost: a test form hosts
        only the test constructs, so a statement stands in a function; an
        expression stands in a function body rather than in a `static`'s
        initializer or a `static_assert`, whose contexts are constants, and a
        pattern in a match arm rather than a destructuring `let`."""
        real = self.g.real(parent)
        name = self.g.info[real].name if real in self.g.info else ""
        return HOST_PENALTY.get(real, 100.0 if name.startswith("syntax.test.") else 0.0)

    def host_chains(self, nt):
        """Chains of frames a nonterminal can stand in, the cheapest first: its
        own cheapest, then one through each other rule that names it."""
        if nt not in self._chains:
            self._chains[nt] = self._host_chains(nt)
        return self._chains[nt]

    def _host_chains(self, nt):
        """The cheapest chain, then chains that leave it at one level: the
        symbol at that level stands in another rule that names it, and from
        there the cheapest way up."""
        start = self.start_of(nt)
        table = self.frames if start == "source-file" else self.start_frames[start]
        cheapest = table[nt]
        chains = [cheapest]
        for level in range(min(len(cheapest), REPAIR_FRAMES) + 1):
            child = nt if level == 0 else cheapest[level - 1][0]
            for parent, ri, k in self.parents(child, table):
                chain = cheapest[:level] + [(parent, ri, k)] + table[parent]
                if chain not in chains and len(chains) < HOST_CHAINS:
                    chains.append(chain)
        return chains

    def parents(self, child, table):
        """(parent, rule index, position) for each place a rule names `child`."""
        out = []
        for parent in sorted(self.g.prods):
            if parent not in table:
                continue
            for ri in self._live(parent):
                for k, sym in enumerate(self.g.prods[parent][ri]):
                    if sym == child:
                        out.append((parent, ri, k))
        return out

    def start_of(self, nt):
        if nt in self.frames:
            return "source-file"
        return next((s for s in START_HOSTS if nt in self.start_frames[s]), None)

    def host(self, chain):
        """[(frame, [sibling trees before], [sibling trees after])] for a chain."""
        out = []
        for parent, ri, k in chain:
            rule = self.g.prods[parent][ri]
            out.append(((parent, ri, k), [self.tree(s) for s in rule[:k]],
                        [self.tree(s) for s in rule[k + 1:]]))
        return out

    def program(self, nt, core, host):
        """Source text for `core`, trees of what nt stands for, in `host`."""
        toks = [t for c in core for t in c.tokens()]
        for _, before, after in host:
            toks = ([t for b in before for t in b.tokens()] + toks
                    + [t for a in after for t in a.tokens()])
        start = self.start_of(nt)
        if start in START_HOSTS:
            inner = format_tokens(toks)[0].strip()
            toks = [t if t != '"{' + HOLE + '}"' else '"{' + inner + '}"'
                    for t in START_HOSTS[start]]
        text, spelled = format_tokens(toks)
        self.intended.setdefault(text, spelled)
        return text

    def token_problem(self, text):
        """Where the lexer reads a generated program's text other than as the
        tokens it was written from, or None: spacing must never join two tokens
        into a third."""
        want = self.intended.get(text)
        if want is None:
            return None
        toks, _ = lexdump.lex_text(text)
        starts = lexdump.line_starts(text)
        got = []
        for n, t in enumerate(toks):
            if t.kind in ("NEWLINE", "EOF"):
                continue
            if t.kind in dump.LITERALS or t.kind == "INTERP_STRING":
                got.append(lexdump.raw_spelling(text, starts, t,
                                                toks[n + 1] if n + 1 < len(toks) else None))
            elif t.kind == "HASH_DIRECTIVE":
                got.append("#" + t.value)
            else:
                got.append(t.value)
        for n in range(max(len(want), len(got))):
            a = want[n] if n < len(want) else "<end>"
            b = got[n] if n < len(got) else "<end>"
            if a != b:
                return "token %d: written %r, read %r" % (n + 1, a, b)
        return None

    # Validation and repair ----------------------------------------------------

    def checked(self, text):
        """The recognizer's recognize.check result for a program, kept for the
        programs checked last."""
        hit = self._checked.pop(text, None)
        if hit is None:
            hit = recognize.check(self.g, text, trees=True)
        self._checked[text] = hit
        while len(self._checked) > CHECKED_KEPT:
            self._checked.popitem(last=False)
        return hit

    def valid(self, text):
        if text not in self.validated:
            self.validated[text] = self.checked(text).verdict == "OK"
        return self.validated[text]

    def realizes(self, text, want):
        """Whether a valid program's tree holds what a case is named for: a
        derivation of the alternative `want` names, (nonterminal, rule index,
        {item index: value}), whose items take those values. A value is
        (kind, rule index or count, whether it writes a token); see `holds`."""
        key = (text, want)
        if key not in self._realized:
            nt, ai, settings = want
            found = False
            for _, parse in self.checked(text).parses:
                for d in recognize.walk_real(self.g, parse.derivations()[0]):
                    if d.nt == nt and d.ai == ai and all(
                            holds(self.g, d.kids[k], v) for k, v in settings):
                        found = True
                        break
                if found:
                    break
            self._realized[key] = found
        return self._realized[key]

    def build(self, nt, core, fixed, want, repair=True):
        """The first program for `core` (a list of trees, one per item of nt's
        rule, those at the indices in `fixed` held) in some host that is valid
        and `realizes` `want`, or None. A repair changes one choice, of an item
        or of a host sibling, and then tries two; without `repair` only the
        cheapest program is tried."""
        def good(text):
            return self.valid(text) and self.realizes(text, want)

        if not repair:
            text = self.program(nt, core, self.host(self.host_chains(nt)[0]))
            return text if good(text) else None
        for chain in self.host_chains(nt):
            host = self.host(chain)
            text = self.program(nt, core, host)
            if good(text):
                return text
            for edit in self._edits(core, fixed, host):
                text = self.program(nt, *edit)
                if good(text):
                    return text
        for chain in self.host_chains(nt)[:PAIR_CHAINS]:
            host = self.host(chain)
            for c1, h1 in itertools.islice(self._edits(core, fixed, host), PAIR_EDITS):
                for c2, h2 in self._edits(c1, fixed, h1):
                    text = self.program(nt, c2, h2)
                    if good(text):
                        return text
        return None

    def _edits(self, core, fixed, host):
        """(core, host) with one choice changed, items first, then the host's
        frames from the innermost out."""
        for k, t in enumerate(core):
            for n in (self.inner_edits(t) if k in fixed else self.neighbours(t)):
                yield core[:k] + [n] + core[k + 1:], host
        for f, (frame, before, after) in enumerate(host[:REPAIR_FRAMES]):
            for side in (0, 1):
                sibs = (before, after)[side]
                for k, t in enumerate(sibs):
                    for n in self.neighbours(t):
                        new = sibs[:k] + [n] + sibs[k + 1:]
                        entry = (frame, new, after) if side == 0 else (frame, before, new)
                        yield core, host[:f] + [entry] + host[f + 1:]

    # Alternatives and their options -------------------------------------------

    def items(self, nt, ai):
        rule = self.g.prods[nt][ai]
        texts = item_texts(self.g.alternative(nt, ai).items)
        assert len(texts) == len(rule), (nt, ai, texts, rule)
        return [Item(k, s, t) for k, (s, t) in enumerate(zip(rule, texts))]

    def options(self, items):
        """(item, kind, [(value name, tree, value)]) for each item with a
        choice, the cheapest value first; `value` is what `holds` checks. An
        optional item's present value, and each unit of a repetition, is the
        cheapest expansion that writes a token, so the value shows in the text.
        An item whose other values name only removed productions has no
        choice: it is held at its one derivable value."""
        out = []
        for it in items:
            sym = it.symbol
            if not sym.startswith("__") or sym.startswith(recognize.SHIFT_AUX):
                continue
            rules = self.g.prods[sym]
            if len(self._live(sym)) < 2:
                continue
            if sym.startswith("__rep"):
                # Grammar._choice writes `x?` as (), (x); `x*` as (), (rep, x);
                # and `x+` as (x), (rep, x).
                if rules[0] == () and rules[1][0] != sym:
                    present = self.filled_tree(sym, 1)
                    if present is None:
                        continue
                    kind = "opt"
                    values = [("absent", Tree(sym, 0), ("opt", 0, False)),
                              ("present", present, ("opt", 1, True))]
                else:
                    kind = "rep"
                    values = [(name, self.repeat(sym, n), ("rep", n, n > 0)) for name, n in
                              ((("0", 0),) if rules[0] == () else ()) + (("1", 1), ("many", MANY))]
            else:
                kind = "choice"
                values = []
                for n, ri in enumerate(self._live(sym)):
                    t = self.tree(sym, ri)
                    values.append(("%d" % (n + 1), t, ("choice", ri, bool(t.tokens()))))
                values.sort(key=lambda v: len(v[1].tokens()))
            out.append((it, kind, values))
        return out

    def repeat(self, sym, n):
        """A repetition of sym written n times, each unit writing a token where
        one can."""
        rules = self.g.prods[sym]
        star = rules[0] == ()

        def unit(s):
            return self.filled_tree(s) or self.tree(s)

        t = Tree(sym, 0, []) if star else Tree(sym, 0, [unit(rules[0][0])])
        for _ in range(n - (0 if star else 1)):
            t = Tree(sym, 1, [t, unit(rules[1][1])])
        return t

    def alternative_cases(self, nt, ai):
        """([(name, program or None)], options) for one alternative: the
        alternative, each value of each option, and the options, for pairing."""
        base = self.g.alternative(nt, ai).effective_name
        items = self.items(nt, ai)
        opts = self.options(items)
        cheapest = {it.index: values[0][1] for it, _, values in opts}

        def core(settings):
            return [settings[it.index][0] if it.index in settings
                    else cheapest.get(it.index) or self.tree(it.symbol) for it in items]

        def case(name, settings):
            want = (nt, ai, tuple(sorted((k, v) for k, (_, v) in settings.items())))
            # A waived case is tried once, so that a waiver that no longer
            # holds shows, without the search a case that has no program costs.
            return self.build(nt, core(settings), set(settings), want,
                              repair=name not in self.waived_cases)

        cases = [(base + "/alt", case(base + "/alt", {}))]
        for it, kind, values in opts:
            for vname, t, value in values:
                name = "%s/%s:%d:%s=%s" % (base, kind, it.index, it.text, vname)
                cases.append((name, case(name, {it.index: (t, value)})))
        return cases, (opts, case)

    def pair_cases(self, per_alt):
        """The cases of a production that set two options of one alternative,
        each to its last value, for every pair in item order."""
        out = []
        for ai, (opts, case) in per_alt:
            base = self.g.alternative(*ai).effective_name
            for (a, _, av), (b, _, bv) in itertools.combinations(opts, 2):
                settings = {a.index: av[-1][1:], b.index: bv[-1][1:]}
                name = "%s/pair:%d:%s=%s,%d:%s=%s" % (base, a.index, a.text, av[-1][0],
                                                      b.index, b.text, bv[-1][0])
                out.append((name, case(name, settings)))
        return out

    def generated_productions(self):
        """The productions that get cases: not removed, and derivable from a
        start symbol a whole program reaches."""
        return [p for p in self.model.productions
                if p.nonterminal is not None and p.status != "removed"
                and p.nonterminal in self.best and self.start_of(p.nonterminal) is not None]

    def production_cases(self, p):
        """[(area, name, program or None)] for one production's non-removed
        alternatives, then its pairs."""
        nt = p.nonterminal
        area = area_of(self.model, p.name)
        out = []
        per_alt = []
        for ai, alt in enumerate(p.alternatives):
            if not generated_alternative(self.g, nt, ai):
                continue
            cases, shape = self.alternative_cases(nt, ai)
            out += [(area, name, prog) for name, prog in cases]
            if shape[0]:
                per_alt.append(((nt, ai), shape))
        return out + [(area, name, prog) for name, prog in self.pair_cases(per_alt)]


def holds(g, d, value):
    """Whether the derivation `d` of an option's item takes `value`: (`opt`,
    rule index, filled), (`rep`, count, filled) or (`choice`, rule index,
    filled), where `filled` asks that it spans at least one token."""
    kind, want, filled = value
    if filled and d.j == d.i:
        return False
    if kind != "rep":
        return d.ai == want
    star = g.prods[d.nt][0] == ()
    count = 0 if star else 1
    while d.ai == 1:
        count += 1
        d = d.kids[0]
    return count == want


def generated_alternative(g, nt, ai):
    """Whether an alternative needs a case: it is not removed, and it names a
    removed production only where it can be absent, inside an item written
    `x?` or `x*`, which its cases hold absent."""
    p = g.info[nt]
    if p.status == "removed":
        return False
    for sym in g.prods[nt][ai]:
        if not is_nonterminal(sym):
            continue
        if _names_removed(g, sym):
            if not (sym.startswith("__rep") and () in g.prods[sym]):
                return False
        elif sym not in g.derivable:
            return False
    return True


def _names_removed(g, sym):
    """Whether an item's symbol names a removed production, in itself or in
    the groups and suffixes it was written with."""
    if sym == recognize.NEVER:
        return True
    if not sym.startswith("__") or sym.startswith(recognize.SHIFT_AUX):
        return False
    return any(_names_removed(g, s) for rule in g.prods[sym] for s in rule if s != sym)


def area_of(model, name):
    """The area file of the production `name`: its GRAMMAR.md section's."""
    line = model.by_name()[name].line
    section = None
    for at, level, text in model.headings:
        if at > line:
            break
        if level == 2:
            section = text.split(".")[0]
    if section not in AREAS:
        raise KeyError("%s is written in section %s, which has no area file" % (name, section))
    return AREAS[section]


# Section-12 cells -------------------------------------------------------------

# Each construct row as an expression or statement: the plain spelling, and for
# the constant grammar of section 5.2 (code C) its constant spelling.
INSTANCES = {
    "syntax.expr.literal": ("1", "1"),
    "syntax.expr.interpolation": ('"{a}"', None),
    "syntax.expr.source-location": ("#line", None),
    "syntax.expr.name": ("a", "a"),
    "syntax.expr.implicit-member": (".a", None),
    "syntax.expr.self": ("self", None),
    "syntax.expr.shorthand-param": ("$0", None),
    "syntax.expr.paren": ("(a)", "(1)"),
    "syntax.expr.tuple": ("(a, b)", None),
    "syntax.expr.array": ("[a]", None),
    "syntax.expr.repeat": ("[a; 2]", None),
    "syntax.expr.map": ("{a: b}", None),
    "syntax.expr.set": ("{a, b}", None),
    "syntax.expr.closure": ("{ a }", None),
    "syntax.expr.call": ("f()", "sizeof<T>()"),
    "syntax.expr.trailing-call": ("f { a }", None),
    "syntax.expr.member": ("a.b", None),
    "syntax.expr.tuple-index": ("a.0", None),
    "syntax.expr.optional-member": ("a?.b", None),
    "syntax.expr.subscript": ("a[b]", None),
    "syntax.expr.force": ("a!", None),
    "syntax.expr.unary": ("-a", "-1"),
    "syntax.expr.deref": ("*a", None),
    "syntax.expr.ref": ("&a", None),
    "syntax.expr.move": ("move a", None),
    "syntax.expr.try": ("try f()", None),
    "syntax.expr.lends": ("lends a", None),
    "syntax.expr.cast": ("a as T", None),
    "syntax.expr.multiplicative": ("a * b", "2 * 3"),
    "syntax.expr.additive": ("a + b", "1 + 2"),
    "syntax.expr.shift": ("a << b", None),
    "syntax.expr.range": ("a..b", None),
    "syntax.expr.range-from": ("a..", None),
    "syntax.expr.range-upto": ("..b", None),
    "syntax.expr.compare": ("a < b", None),
    "syntax.expr.bitand": ("a & b", None),
    "syntax.expr.bitxor": ("a ^ b", None),
    "syntax.expr.bitor": ("a | b", None),
    "syntax.expr.and": ("a && b", None),
    "syntax.expr.or": ("a || b", None),
    "syntax.expr.coalesce": ("a ?? b", None),
    "syntax.expr.if": ("if a { b } else { c }", None),
    "syntax.expr.match": ("match a { case _ -> b }", None),
    "syntax.expr.while": ("while a { }", None),
    "syntax.expr.while-let": ("while let x = a { }", None),
    "syntax.expr.for": ("for x in a { }", None),
    "syntax.borrow.for": ("for borrow let x in a { }", None),
    "syntax.expr.try-block": ("try { a } catch { b }", None),
    "syntax.borrow.place": ("borrow let a[0]", None),
    "syntax.borrow.block": ("borrow let x = a { x }", None),
    "syntax.expr.optional-binding": ("let x = a", None),
    "syntax.borrow.unwrap": ("borrow let x = a", None),
    "syntax.stmt.let": ("let x = a", None),
    "syntax.stmt.destructure": ("let (x, y) = a", None),
    "syntax.stmt.assign": ("a = b", None),
    "syntax.stmt.compound-assign": ("a += b", None),
    "syntax.stmt.return": ("return a", None),
    "syntax.stmt.break": ("break", None),
    "syntax.stmt.continue": ("continue", None),
    "syntax.stmt.lend": ("lend a", None),
    "syntax.stmt.guard": ("guard let x = a else { return }", None),
    "syntax.stmt.guard-condition": ("guard a else { return }", None),
    "syntax.decl.static-assert": ('static_assert(a, "m")', None),
    "syntax.stmt.attributed-local": ("@align(8) let x = a", None),
    "syntax.stmt.optional-assign": ("a?.b = c", None),
    "syntax.expr.capture": ("a", None),
}


def in_function(body):
    """A whole program whose one function holds `body`, a statement per line."""
    return "func f() {\n%s\n}\n" % "\n".join("    " + line for line in body.split("\n"))


# The programs a context's cell is placed in, tried in order; HOLE marks the
# construct. A construct binds tighter or looser than an operator, so the
# operand and right-side contexts try one host operator after another until
# the construct stands as the operand itself.
CONTEXTS = {
    "stmt": [in_function(HOLE + "\nx")],
    "tail": [in_function(HOLE)],
    "clos": [in_function("let c = {\n    " + HOLE + "\n    x\n}")],
    "catch": [in_function("try {\n    x\n} catch {\n    " + HOLE + "\n    x\n}")],
    "arm": [in_function("match x {\n    case _ -> " + HOLE + "\n}")],
    "opnd": [in_function("let v = " + t) for t in (
        HOLE + " * x", "x == " + HOLE, HOLE + " & x", HOLE + " ^ x", HOLE + " | x",
        HOLE + " && x", HOLE + " || x", HOLE + " ?? x", "-" + HOLE, HOLE + " as T")],
    "rhs": [in_function("let v = " + t) for t in (
        "x && " + HOLE, "x || " + HOLE, "x ?? " + HOLE)],
    "arg": [in_function("f(" + HOLE + ")")],
    "larg": [in_function("f(a: " + HOLE + ")")],
    "elem": [in_function("let v = [" + HOLE + "]")],
    "recv": [in_function("let v = " + HOLE + ".b")],
    "idx": [in_function("let v = a[" + HOLE + "]")],
    "interp": [in_function('print("{' + HOLE + '}")')],
    "cond": [in_function("if " + HOLE + " {\n}")],
    "subj": [in_function("if let x = " + HOLE + " {\n}")],
    "scrut": [in_function("match " + HOLE + " {\n    case _ -> x\n}")],
    "aguard": [in_function("match x {\n    case _ if " + HOLE + " -> x\n}")],
    "iter": [in_function("for i in " + HOLE + " {\n}")],
    "rend": [in_function("for i in " + HOLE + "..x {\n}"),
             in_function("for i in x.." + HOLE + " {\n}")],
    "bhead": [in_function("borrow let x = " + HOLE + " {\n}")],
    "init": [in_function("let v = " + HOLE)],
    "asgn": [in_function("v = " + HOLE)],
    "crhs": [in_function("v += " + HOLE)],
    "atgt": [in_function(HOLE + " = x"), in_function(HOLE + " += x")],
    "ret": [in_function("return " + HOLE)],
    "brk": [in_function("while x {\n    break " + HOLE + "\n}")],
    "lend": [in_function("lend " + HOLE)],
    "try": [in_function("let v = try " + HOLE)],
    "dflt": ["func f(p: T = " + HOLE + ") {\n}\n"],
    "sinit": ["static S: T = " + HOLE + "\n"],
    "alen": [in_function("let v: [T; " + HOLE + "] = w")],
    "rcnt": [in_function("let v = [x; " + HOLE + "]")],
    "cgen": [in_function("let v: A<" + HOLE + "> = w"), in_function("let v = A<" + HOLE + ">()"),
             "func f<const N: Int = " + HOLE + ">() {\n}\n"],
    "raw": ["enum E: T {\n    case A = " + HOLE + "\n}\n"],
    "aarg": ["@align(" + HOLE + ")\nstatic S: T = x\n"],
    "sassert": ["static_assert(" + HOLE + ', "m")\n'],
    "cap": [in_function("let c = { [" + HOLE + "] in x }")],
}
ALLOWED = "YSKTPHC"


def matrix(model):
    """[(construct, context, code)] for each allowed cell, in table order."""
    table = model.tables_of(extract.MATRIX)[0]
    contexts = table.header[1:]
    out = []
    for _, cells in table.rows:
        for ctx, code in zip(contexts, cells[1:]):
            if code in ALLOWED:
                out.append((cells[0], ctx, code))
    return out


def records(checked):
    """(alternatives, cells) the trees of a valid program record, its
    segments' included, from its recognize.check result."""
    alts, cells = set(), set()
    for _, parse in checked.parses:
        for d in parse.derivations()[:1]:
            rec = parse.record(d)
            alts.update(rec.alternatives)
            cells.update((c, ctx) for c, ctx, _, _ in rec.cells)
    return alts, cells


def cell_case(gen, construct, ctx, code):
    """(area, name, program or None): an allowed cell's construct placed in its
    context, parenthesized when the code is P or when no host places it bare.
    A program counts only when its record holds the cell."""
    plain, constant = INSTANCES[construct]
    instance = constant if code == "C" and constant else plain
    forms = ["(%s)" % instance] if code == "P" else [instance, "(%s)" % instance]
    found = None
    for form in forms:
        for template in CONTEXTS[ctx]:
            text = template.replace(HOLE, form)
            if gen.valid(text) and (construct, ctx) in records(gen.checked(text))[1]:
                found = text
                break
        if found:
            break
    return area_of(gen.model, construct), "%s/cell:%s" % (construct, ctx), found


# Jobs ---------------------------------------------------------------------------

def jobs(gen):
    """The generation jobs in corpus order: each production, then each cell."""
    out = ["production\t" + p.nonterminal for p in gen.generated_productions()]
    out += ["cell\t%s\t%s\t%s" % c for c in matrix(gen.model)]
    return out


def run_job(gen, job):
    """[[area, name, program or None, dump lines or failure, alternatives,
    cells]] for one job; the last three describe the program when there is one."""
    fields = job.split("\t")
    if fields[0] == "production":
        p = gen.g.info[fields[1]]
        cases = gen.production_cases(p)
    else:
        cases = [cell_case(gen, *fields[1:])]
    out = []
    for area, name, text in cases:
        if text is None:
            out.append([area, name, None, None, [], []])
            continue
        checked = gen.checked(text)
        try:
            lines = dump.source_dump(gen.g, text, checked=checked)
            problem = gen.token_problem(text)
            if problem:
                lines = "the lexer does not read the generated tokens: " + problem
        except dump.Failure as e:
            lines = str(e)
        alts, cells = records(checked)
        out.append([area, name, text, lines, sorted(alts), sorted(list(c) for c in cells)])
    return out


def run_worker():
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    gen = Generator(recognize.Grammar(extract.extract()), waived_case_names())
    for line in sys.stdin:
        sys.stdout.write(json.dumps(run_job(gen, line.rstrip("\n"))) + "\n")
    return 0


def generate(jobs_count=None):
    """Every case in corpus order, as the lists run_job returns."""
    gen = Generator(recognize.Grammar(extract.extract()))
    todo = jobs(gen)
    results = recognize.run_workers([os.path.abspath(__file__), "--worker"], todo,
                                    jobs_count or recognize.default_jobs())
    return [case for result in results for case in result]


# Formatting -------------------------------------------------------------------

NO_SPACE_BEFORE = (",", ")", "]", ";", ":", ".", "?.", "?", "!")
NO_SPACE_AFTER = ("(", "[", ".", "?.", "@")


def names():
    """Identifier spellings in order: a to z, then a1, b1, and so on."""
    for n in itertools.count():
        for c in "abcdefghijklmnopqrstuvwxyz":
            yield c if n == 0 else "%s%d" % (c, n)


def format_tokens(tokens):
    """Source text for a token list: one space between tokens, none inside
    brackets, around a member `.` or before a call's `(`, a line break with
    indentation for each `\\n`, and each identifier named afresh. Line breaks
    before the first token and after the last stay, since a case may be about
    them; a text whose tokens end in none ends in one line break."""
    fresh = names()
    out = []
    spelled = []
    depth = 0
    line = ""
    prev = None
    for tok in tokens:
        if tok == "":
            continue
        if tok == "\n":
            out.append(line.rstrip())
            line = ""
            prev = None
            continue
        callee = prev == IDENT or prev in (")", "]")
        if tok == IDENT:
            text = next(fresh)
        else:
            text = tok
        # The lexer has no shift token; a shift is two touching halves.
        spelled.extend([text[0], text[1]] if text in ("<<", ">>") else [text])
        if tok == "}":
            depth = max(0, depth - 1)
        # A `.` after `{` starts an implicit member, and a `?` after a `?`
        # would join it into `??`.
        glued = (tok in NO_SPACE_BEFORE and not (tok == "." and prev == "{")
                 and not (tok == "?" and prev == "?"))
        if not line:
            line = "    " * depth + text
        elif prev in NO_SPACE_AFTER or glued or (tok in ("(", "[") and callee):
            line += text
        else:
            line += " " + text
        if tok == "{":
            depth += 1
        prev = tok
    out.append(line.rstrip())
    text = "\n".join(out)
    return text if text.endswith("\n") else text + "\n", spelled


# The corpus files -------------------------------------------------------------

def area_files(cases):
    """{file name: text} for the generated corpus: each area's cases, then
    their dumps, in corpus order."""
    blocks = {}
    for area, name, text, lines, _, _ in cases:
        if text is None or not isinstance(lines, list):
            continue
        saw, dmp = blocks.setdefault(area, ([], []))
        saw.append(HEADER + name + "\n" + text)
        dmp.append(HEADER + name + "\n" + "\n".join(lines) + "\n")
    out = {}
    for _, area in sorted(AREAS.items()):
        if area in blocks:
            saw, dmp = blocks[area]
            out[area + ".saw"] = "\n".join(saw)
            out[area + ".dump"] = "\n".join(dmp)
    return out


def read_cases(path):
    """[(name, text)] of an area file: each case runs from its header to the
    line before the next header, less the blank line that separates them.
    This is how a parser's corpus runner reads them; `round_trip` checks it."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    cases = []
    for line in lines:
        if line.startswith(HEADER):
            cases.append((line[len(HEADER):], []))
        elif cases:
            cases[-1][1].append(line)
    # A case's text ends in a line break, so its last line and the separating
    # blank line, or the file's end, join back into exactly that text.
    return [(name, "\n".join(body)) for name, body in cases]


def problems(cases, waivers):
    """Failure lines for cases that have no program or no dump, unless a waiver
    covers them."""
    out = []
    for area, name, text, lines, _, _ in cases:
        if text is None:
            if not waived(name, waivers):
                out.append("generated case %s: no program has exactly one tree "
                           "(fix the generator, or waive its item)" % name)
        elif not isinstance(lines, list):
            out.append("generated case %s: %s" % (name, lines))
    return out


def waived(case_name, waivers):
    """Whether the case, or the item it stands for, is waived."""
    base, _, variant = case_name.partition("/")
    if ("case", case_name) in waivers:
        return True
    if variant.startswith("cell:"):
        return ("cell", "%s %s" % (base, variant[5:])) in waivers
    return ("alternative", base) in waivers


def compare(files):
    """Failure lines where compiler/tests/parse/generated/ differs from `files`."""
    out = []
    present = sorted(os.listdir(GENERATED)) if os.path.isdir(GENERATED) else []
    for name in sorted(set(files) | set(present)):
        rel = os.path.relpath(os.path.join(GENERATED, name), extract.REPO)
        if name not in files:
            out.append("%s: not generated any more; run %s" % (rel, REGENERATE))
            continue
        if name not in present:
            out.append("%s: missing; run %s" % (rel, REGENERATE))
            continue
        with open(os.path.join(GENERATED, name), encoding="utf-8") as fh:
            have = fh.read()
        if have != files[name]:
            out.append("%s: regenerating it differs at %s; run %s and review the diff"
                       % (rel, first_difference(have, files[name]), REGENERATE))
    return out


REGENERATE = "compiler/tests/grammar/generate.py"


def round_trip(cases):
    """Failure lines where reading an area file back, as a parser's runner
    does, does not give its cases."""
    out = []
    for _, area in sorted(AREAS.items()):
        path = os.path.join(GENERATED, area + ".saw")
        want = [(name, text) for a, name, text, lines, _, _ in cases
                if a == area and text is not None and isinstance(lines, list)]
        if want and read_cases(path) != want:
            out.append("%s: reading its cases back does not give the generated cases"
                       % os.path.relpath(path, extract.REPO))
    return out


def first_difference(have, want):
    a, b = have.split("\n"), want.split("\n")
    for n in range(max(len(a), len(b))):
        x = a[n] if n < len(a) else "<end>"
        y = b[n] if n < len(b) else "<end>"
        if x != y:
            return "line %d: %r, regenerated %r" % (n + 1, x[:80], y[:80])
    return "the end"


# Coverage ---------------------------------------------------------------------

WAIVERS = os.path.join(PARSE_DIR, "waivers.tsv")
WAIVER_HEADER = "kind\titem\treason"
# An `alternative` or a `cell` is a coverage item; a `case` is one case, by
# name, that no program realizes.
WAIVER_KINDS = ("alternative", "cell", "case")


def waived_case_names(path=WAIVERS):
    return {item for kind, item in load_waivers(path)[0] if kind == "case"}


def load_waivers(path=WAIVERS):
    """({(kind, item): reason}, [complaint])."""
    rows, complaints = {}, []
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    rel = os.path.relpath(path, extract.REPO)
    if lines[0] != WAIVER_HEADER:
        complaints.append("%s: the first line must be %r" % (rel, WAIVER_HEADER))
    for n, line in enumerate(lines[1:], 2):
        if not line:
            continue
        cells = line.split("\t")
        if len(cells) != 3 or cells[0] not in WAIVER_KINDS or not cells[2].strip():
            complaints.append("%s:%d: want `alternative`, `cell` or `case`, the item, and a "
                              "reason, tab-separated" % (rel, n))
        elif (cells[0], cells[1]) in rows:
            complaints.append("%s:%d: %s is waived twice" % (rel, n, cells[1]))
        else:
            rows[(cells[0], cells[1])] = cells[2]
    return rows, complaints


def coverage(g, cases, waivers):
    """(failure lines, counts): each non-removed alternative must be used by a
    case, and each allowed section-12 cell recorded by one, unless waived; a
    waiver for a covered or unknown item fails too."""
    alternatives = sorted({g.alternative(p.nonterminal, ai).effective_name
                           for p in g.model.productions if p.nonterminal
                           for ai in range(len(p.alternatives))
                           if generated_alternative(g, p.nonterminal, ai)})
    cells = sorted({"%s %s" % (c, ctx) for c, ctx, _ in matrix(g.model)})
    used_alts, used_cells = set(), set()
    for _, _, text, lines, alts, recorded in cases:
        if text is not None and isinstance(lines, list):
            used_alts.update(alts)
            used_cells.update("%s %s" % (c, ctx) for c, ctx in recorded)
    out = []
    for kind, items, used in (("alternative", alternatives, used_alts),
                              ("cell", cells, used_cells)):
        for item in items:
            if item not in used and (kind, item) not in waivers:
                out.append("parsecoverage: the %s %s has no generated case and no waiver"
                           % (kind, item))
            elif item in used and (kind, item) in waivers:
                out.append("parsecoverage: the %s %s is covered, so its waiver goes" % (kind, item))
        for k, item in sorted(waivers):
            if k == kind and item not in items:
                out.append("parsecoverage: the waived %s %s is not one the check asks for"
                           % (kind, item))
    realized = {name for _, name, text, _, _, _ in cases if text is not None}
    unrealized = {name for _, name, text, _, _, _ in cases if text is None}
    for k, name in sorted(waivers):
        if k != "case":
            continue
        if name in realized:
            out.append("parsecoverage: the case %s has a program, so its waiver goes" % name)
        elif name not in unrealized:
            out.append("parsecoverage: the waived case %s is not a generated case" % name)
    counts = {"covered alternatives": len(set(alternatives) & used_alts),
              "covered cells": len(set(cells) & used_cells),
              "waivers": len(waivers)}
    return out, counts


def check(jobs_count=None):
    """(failure lines, counts): regenerating reproduces generated/, every case
    has its program and dump, and coverage holds."""
    cases = generate(jobs_count)
    waivers, failures = load_waivers()
    failures += problems(cases, waivers)
    failures += compare(area_files(cases))
    if not failures:
        failures += round_trip(cases)
    covered, counts = coverage(recognize.Grammar(extract.extract()), cases, waivers)
    failures += covered
    counts["generated cases"] = sum(1 for c in cases if c[2] is not None)
    return failures, counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="compare, and check coverage")
    ap.add_argument("--jobs", type=int, default=recognize.default_jobs())
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    if args.worker:
        return run_worker()
    if args.check:
        failures, counts = check(args.jobs)
        for f in failures:
            print(f)
        summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
        print("parse corpus: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                        summary))
        return 1 if failures else 0
    cases = generate(args.jobs)
    waivers, failures = load_waivers()
    failures += problems(cases, waivers)
    if failures:
        for f in failures:
            print(f)
        print("parse corpus: nothing written: %d problem(s)" % len(failures))
        return 1
    files = area_files(cases)
    os.makedirs(GENERATED, exist_ok=True)
    for name in os.listdir(GENERATED):
        if name not in files:
            os.unlink(os.path.join(GENERATED, name))
    for name, text in sorted(files.items()):
        with open(os.path.join(GENERATED, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    size = sum(len(t.encode("utf-8")) for t in files.values())
    print("parse corpus: wrote %d case(s) to %d file(s), %d bytes"
          % (sum(1 for c in cases if c[2] is not None), len(files), size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
