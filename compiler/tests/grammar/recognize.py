#!/usr/bin/env python3
"""The reference recognizer: an Earley parser built from GRAMMAR.md's fences.

    python compiler/tests/grammar/recognize.py FILE... | --list LISTFILE [--root DIR]
    python compiler/tests/grammar/recognize.py --trees [--record] [--start NT] (FILE... | --text T)

The chart reads the self-hosted lexer's tokens (`lexdump`) after `prepare`
applies section 2.4's newline rules and the generic-close split. Its
derivations become trees, shaped by `node=`, after the section-13 rules in
PREFERENCES and FILTERS; a text is accepted only when a tree survives them, and
more than one tree is a finding. `--trees` prints each tree as the canonical
dump of compiler/tests/parse/README.md (dump.py).
A `Record` is one tree's coverage data: `alternatives` counts each alternative
name the derivation used, and `cells` lists each context-matrix construct as
(construct, section-12 context, parenthesized, "line:col"), the contexts coming
from `contexts.py`. `source_parses` adds a file's interpolation segments, each a
parse of its own.
"""
import argparse
import collections
import concurrent.futures
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import contexts  # noqa: E402
import extract  # noqa: E402
import lexdump  # noqa: E402
from lexdump import Token  # noqa: E402

# Distinct trees kept per span. Two already make a finding, so the cap bounds
# the enumeration without hiding one.
TREE_CAP = 8
# Tree building recurses once per element of the longest list in a file.
RECURSION_LIMIT = 50000
# Productions written `operand ( op operand )*` build their node only with a
# second operand (section 1, Nodes).
CHAINS = {"Binary", "Coalesce", "Cast", "Range"}
# Productions whose `?` suffixes wrap the type before them, in the node
# syntax.type.suffix names.
SUFFIXED = {"syntax.type.type", "syntax.type.cast-target"}
OPTIONAL_TYPE = "OptionalType"
NEVER = "__NEVER"
# Terminals that are never a leaf, and the punctuation that is one only in a
# production the tree needs it for (Grammar.shown); separators never are.
LAYOUT = ("NEWLINE", "EOF")
PUNCTUATION = ("(", ")", "[", "]", "{", "}", "<", ">", ",", ";", ":", ".", "->", "@")
SEPARATORS = (",", ";")
# Section-13 rules that choose between readings of one span: nonterminal ->
# (the alternative kept when it is one of the readings, the rules it applies).
PREFERENCES = {
    "generic-arg": ("syntax.generic.arg.type", ("syntax.rule.generic-arg-value",)),
    "pattern": ("syntax.pat.pattern.wildcard", ("syntax.rule.name-pattern",)),
    "non-expr-statement": ("syntax.stmt.non-expr.optional-assign",
                           ("syntax.rule.optional-chain-run",)),
}
# Rules that refuse a derivation: (nonterminal, method of Forest, rule). The
# method returns None when the derivation stands, else the index of the token
# the rule refuses it at. A text the chart accepts is refused when no tree
# survives these, so they decide acceptance as well as trees.
FILTERS = [
    ("compare-expr", "_generic_or_less", "syntax.rule.generic-or-less"),
    ("cast-target", "_cast_list", "syntax.rule.generic-or-less"),
    ("name-expr", "_generic_kept", "syntax.rule.generic-or-less"),
    ("member-hop", "_generic_kept", "syntax.rule.generic-or-less"),
    ("optional-hop", "_generic_kept", "syntax.rule.generic-or-less"),
    ("postfix-expr", "_trailing_closure", "syntax.rule.trailing-closure"),
    ("projection-target", "_trailing_closure", "syntax.rule.trailing-closure"),
    ("call-target", "_trailing_closure", "syntax.rule.trailing-closure"),
    ("optional-chain-target", "_trailing_closure", "syntax.rule.trailing-closure"),
    ("head-expr", "_head_restriction", "syntax.rule.head-restriction"),
    ("binding-subject", "_head_restriction", "syntax.rule.head-restriction"),
    ("borrow-place", "_borrow_form", "syntax.rule.borrow-form"),
    ("try-expr", "_try_block", "syntax.rule.try-block"),
    ("lends-expr", "_lends_word", "syntax.rule.contextual-words"),
    ("statement", "_static_assert_word", "syntax.rule.contextual-words"),
    ("arm-body", "_static_assert_word", "syntax.rule.contextual-words"),
    ("arm-body", "_arm_body", "syntax.rule.arm-body"),
    ("cast-suffix", "_cast_question", "syntax.rule.cast-target-question"),
    ("range-from", "_range_open_end", "syntax.rule.range-open-end"),
    ("range-upto", "_range_open_end", "syntax.rule.range-open-end"),
    ("let-stmt", "_discard_binding", "syntax.rule.discard-binding"),
    ("extern-block", "_extern_abi", "syntax.rule.extern-abi"),
    ("declaration-item", "_attribute_position", "syntax.rule.attribute-position"),
    ("attributed-local", "_attribute_position", "syntax.rule.attribute-position"),
    ("func-decl", "_receiver_and_static", "syntax.rule.receiver-and-static"),
    ("init-decl", "_receiver_and_static", "syntax.rule.receiver-and-static"),
    ("method-decl", "_receiver_and_static", "syntax.rule.receiver-and-static"),
    ("requirement", "_receiver_and_static", "syntax.rule.receiver-and-static"),
    ("func-decl", "_effect_placement", "syntax.rule.effect-slot"),
    ("init-decl", "_effect_placement", "syntax.rule.effect-slot"),
    ("method-decl", "_effect_placement", "syntax.rule.effect-slot"),
    ("requirement", "_requirement_consumes", "syntax.rule.requirement-borrows"),
    ("try-route", "_try_route_case", "syntax.rule.try-route-case"),
    ("import-target", "_import_names", "syntax.rule.import-names"),
]
# Rules applied outside the two tables: in `prepare`, in the chart's terminals,
# in the head walk, and against the doc comments.
OTHER_RULES = ("syntax.rule.generic-close-split", "syntax.rule.head-reset",
               "syntax.lex.shift-adjacent", "syntax.lex.module-doc", "syntax.lex.doc-attach")
# Rules the tests switch off, one at a time, to see each one decide something.
DISABLED = set()


def applies(rule):
    return rule not in DISABLED


# A trailing closure's callee: a name, an implicit member (these two primaries),
# a member or an optional member (syntax.rule.trailing-closure).
TRAILING_CALLEES = {"syntax.expr.primary.name", "syntax.expr.primary.implicit-member"}
# The hop productions a hop derivation bottoms out in, by the kind of callee
# each makes; every other hop makes a callee that takes no trailing closure.
LEAF_HOPS = {"member-hop": "member", "optional-hop": "member", "call-hop": "call",
             "trailing-hop": "trailing"}
# Inside a head, these start a fresh level where trailing closures attach again
# (syntax.rule.head-reset): the brackets, a call's arguments, and each nested
# brace-delimited block: a closure body, a match's arms, and every construct's
# `block`.
HEAD_RESETS = ("paren-expr", "tuple-expr", "array-literal", "repeat-literal",
               "closure-literal", "arg-list", "subscript-hop", "block", "match-arm-list")
# Where a generic list after a name or member is kept in an expression, and so
# is speculative until it closes (syntax.rule.generic-or-less).
GENERIC_HOSTS = ("name-expr", "member-hop", "optional-hop")
GENERIC_FOLLOW = ("(", ".", "{")
# A type whose `<` is speculative, as an expression name's is.
CAST_TARGET = "cast-target"
# The start symbols the recognizer parses from, which FOLLOW sets are taken over.
STARTS = ("source-file", "interp-segment", "refusal-unit")
# The tokens after `..` that let a range omit its upper bound, besides a line
# break and the end of input (syntax.rule.range-open-end).
OPEN_END_FOLLOW = ("]", ")", ",", ";", "}")
# attribute alternative -> its name, and the names each attributed declaration
# takes (syntax.rule.attribute-position).
ATTRIBUTE_NAMES = {
    "syntax.attr.attribute.export": "export",
    "syntax.attr.attribute.export-symbol": "export",
    "syntax.attr.attribute.section": "section",
    "syntax.attr.attribute.synthesize": "synthesize",
    "syntax.attr.attribute.align": "align",
    "syntax.attr.attribute.synthesize-shared": "synthesize-shared",
}
ATTRIBUTE_HOSTS = {
    "syntax.decl.item.func": ("export", "section"),
    "syntax.decl.item.static": ("export", "section", "align"),
    "syntax.decl.item.extension": ("synthesize",),
    "syntax.stmt.attributed-local": ("align",),
}
# A refused receiver is still receiver-shaped, so that the rule on where
# receivers stand leaves its own refusal to it.
RECEIVERS = ("syntax.decl.param.receiver", "syntax.decl.param.refused-receiver")
# The declarations a `///` run documents: an alternative, or a whole production
# (syntax.lex.doc-attach).
DOCUMENTED = {"syntax.decl.item.func", "syntax.decl.item.static",
              "syntax.decl.item.extension", "syntax.decl.item.struct",
              "syntax.decl.item.enum", "syntax.decl.item.trait",
              "syntax.decl.item.type-alias", "syntax.decl.extension-member.method",
              "syntax.decl.extension-member.synthesized-method",
              "syntax.decl.extension-member.init", "syntax.decl.trait-member.requirement",
              "syntax.decl.field", "syntax.decl.case"}
TEST_ONLY_DECLARATION = "syntax.test.declaration.item"
# The alternatives that read a statement position as an expression.
EXPRESSION_STATEMENTS = ("syntax.stmt.statement.expr", "syntax.expr.arm-body.expr")


def is_nonterminal(sym):
    return sym.startswith("__") or bool(extract.NONTERMINAL_RE.match(sym))


class Grammar:
    """The productions as Earley rules: nonterminal -> [symbol tuple, ...].

    Groups and suffixes become auxiliary nonterminals named `__...`, each owned
    by the alternative it was written in (`owner`). A `removed` production is
    unreachable unless named in `enable` ("all" enables every one).
    """

    def __init__(self, model, enable=()):
        self.model = model
        self.prods = {}
        self.owner = {}   # aux nonterminal -> (nonterminal, alternative index)
        self.info = {}    # nonterminal -> Production
        self.counter = 0
        status = {p.nonterminal: p.status for p in model.productions if p.nonterminal}
        disabled = {nt for nt, st in status.items() if st == "removed"
                    and enable != "all" and nt not in enable}
        for p in model.productions:
            if p.nonterminal is None:
                continue
            self.info[p.nonterminal] = p
            out = []
            for ai, alt in enumerate(p.alternatives):
                seq = self._sequence(alt.items, disabled, (p.nonterminal, ai))
                out.append(tuple(seq))
            self.prods[p.nonterminal] = out
        self.nullable = self._nullable()
        self.derivable = self._derivable()
        self.first = self._first()
        self.flagged = self._flagged()
        by_name = {p.name: p for p in model.productions}
        self.run_opens = {by_name[n].node for n in RUN_OPENS}
        self.run_closes = {by_name[n].node for n in RUN_CLOSES}
        self.cast_list_follow = self._local_follow(CAST_TARGET, "generic-args",
                                                   self._follow(STARTS)[CAST_TARGET])

    def _fresh(self, base, owner):
        self.counter += 1
        nt = "__%s%d" % (base, self.counter)
        self.owner[nt] = owner
        return nt

    def _sequence(self, items, disabled, owner):
        alts, pos = self._choice(items, 0, disabled, owner)
        assert pos == len(items), items
        if len(alts) != 1:
            nt = self._fresh("alt", owner)
            self.prods[nt] = [tuple(a) for a in alts]
            return [nt]
        return alts[0]

    def _choice(self, items, pos, disabled, owner):
        alts = []
        cur = []
        while pos < len(items) and items[pos] != ")":
            t = items[pos]
            if t == "|":
                alts.append(cur)
                cur = []
                pos += 1
                continue
            if t == "(":
                inner, pos = self._choice(items, pos + 1, disabled, owner)
                assert items[pos] == ")"
                pos += 1
                sym = self._fresh("grp", owner)
                self.prods[sym] = [tuple(a) for a in inner]
            elif t == "ε":
                pos += 1
                continue
            else:
                pos += 1
                if extract.NONTERMINAL_RE.match(t):
                    sym = NEVER if t in disabled else t
                elif t in ("SHL", "SHR"):
                    # The lexer has no shift token: a shift is a `<` or `>` and
                    # a second one touching it (syntax.lex.shift-adjacent).
                    sym = self._fresh(t.lower(), owner)
                    self.prods[sym] = [(SHIFT_HALF[t], SHIFT_SECOND[t])]
                else:
                    sym = t
            if pos < len(items) and items[pos] in ("?", "*", "+"):
                op = items[pos]
                pos += 1
                nt = self._fresh("rep", owner)
                if op == "?":
                    self.prods[nt] = [(), (sym,)]
                elif op == "*":
                    self.prods[nt] = [(), (nt, sym)]
                else:
                    self.prods[nt] = [(sym,), (nt, sym)]
                sym = nt
            cur.append(sym)
        alts.append(cur)
        return alts, pos

    def _nullable(self):
        nullable = set()
        changed = True
        while changed:
            changed = False
            for nt, alts in self.prods.items():
                if nt in nullable:
                    continue
                for a in alts:
                    if all(s in nullable for s in a):
                        nullable.add(nt)
                        changed = True
                        break
        return nullable

    def _derivable(self):
        """The nonterminals that derive some token sequence, a rule naming a
        removed production never counting."""
        derivable = set()
        changed = True
        while changed:
            changed = False
            for nt, alts in self.prods.items():
                if nt not in derivable and any(
                        all(not is_nonterminal(s) or s in derivable for s in a) for a in alts):
                    derivable.add(nt)
                    changed = True
        return derivable

    def _live(self, nt):
        """The rules of nt that can derive something: none names a removed production."""
        return [a for a in self.prods[nt] if NEVER not in a]

    def _first(self):
        first = {nt: set() for nt in self.prods}
        changed = True
        while changed:
            changed = False
            for nt in self.prods:
                for alt in self._live(nt):
                    add = self.first_of(alt, first)
                    if not add <= first[nt]:
                        first[nt] |= add
                        changed = True
        return first

    def first_of(self, seq, first=None):
        """The terminals a sequence of symbols can start with."""
        first = self.first if first is None else first
        out = set()
        for sym in seq:
            if not is_nonterminal(sym):
                out.add(sym)
                return out
            out |= first[sym]
            if sym not in self.nullable:
                return out
        return out

    def _ends(self, alt, k):
        """Whether the symbols of alt after k can all be empty."""
        return all(s in self.nullable for s in alt[k + 1:])

    def _follow(self, starts):
        """FOLLOW of every nonterminal reachable from `starts`."""
        region = set()
        pending = list(starts)
        while pending:
            nt = pending.pop()
            if nt not in region:
                region.add(nt)
                for alt in self._live(nt):
                    pending.extend(s for s in alt if is_nonterminal(s))
        return self._follow_over(region, {s: set() for s in starts})

    def _local_follow(self, top, target, top_follow):
        """What can follow a `target` that can end a `top` whose own follow is
        `top_follow`. Only the productions of nonterminals that can end a `top`
        contribute, so a `?` after the target counts and what follows a list
        nested in the target's own list does not."""
        region = set()
        pending = [top]
        while pending:
            nt = pending.pop()
            if nt in region:
                continue
            region.add(nt)
            if nt == target:
                continue
            for alt in self._live(nt):
                for k, sym in enumerate(alt):
                    if is_nonterminal(sym) and self._ends(alt, k):
                        pending.append(sym)
        return self._follow_over(region, {top: set(top_follow)})[target]

    def _follow_over(self, region, seeds):
        follow = collections.defaultdict(set)
        for nt, terms in seeds.items():
            follow[nt] |= terms
        changed = True
        while changed:
            changed = False
            for nt in sorted(region):
                for alt in self._live(nt):
                    for k, sym in enumerate(alt):
                        if sym not in region:
                            continue
                        add = self.first_of(alt[k + 1:])
                        if self._ends(alt, k):
                            add = add | follow[nt]
                        if not add <= follow[sym]:
                            follow[sym] |= add
                            changed = True
        return follow

    def alternative(self, nt, ai):
        """The Alternative a real nonterminal's rule index stands for."""
        return self.info[nt].alternatives[ai]

    def real(self, nt):
        """The real nonterminal an auxiliary one was written in, or nt itself."""
        return self.owner[nt][0] if nt.startswith("__") else nt

    def suffix(self, nt, ai):
        """The Kind suffix of a node nt builds by rule ai: the alternative's last
        name segment when the production has more than one alternative."""
        p = self.info[nt]
        if len(p.alternatives) < 2:
            return ""
        return p.alternatives[ai].effective_name.rsplit(".", 1)[1]

    def chain_alternative(self, nt, ai):
        """Whether rule ai of nt is written `operand ( op operand )*` or with `?`,
        or `operand suffix*`: an operand, then one repetition."""
        rule = self.prods[nt][ai]
        return len(rule) == 2 and is_nonterminal(rule[0]) and rule[1].startswith("__rep")

    def shown(self, nt, sym):
        """Whether a token that terminal `sym` matched in a rule of nt is a leaf
        of the tree (compiler/tests/parse/README.md, Leaves)."""
        if sym in LAYOUT:
            return False
        if not (sym.startswith('"') or sym.startswith("'")):
            return True
        owner = self.real(nt)
        if sym[1:-1] in PUNCTUATION:
            return owner in self.flagged and sym[1:-1] not in SEPARATORS
        return nt.startswith("__") or self.info[owner].node == "-"

    def _flagged(self):
        """The `node=-` productions whose punctuation is a leaf: one that can
        derive punctuation and print nothing else, one with two alternatives the
        rest of the tree cannot tell apart, and what their single-nonterminal
        alternatives name (compiler/tests/parse/README.md, Leaves)."""
        quiet, marked = self._quiet()
        flagged = set()
        for nt, p in self.info.items():
            if p.node != "-" or p.status == "removed" or self._layout_only(nt):
                continue
            rules = self._live(nt)
            if marked.get(nt):
                flagged.add(nt)
            skeletons = [self._skeleton(rule, quiet) for rule in rules]
            if len(set(skeletons)) < len(skeletons):
                flagged.add(nt)
        pending = sorted(flagged)
        while pending:
            nt = pending.pop()
            for rule in self._live(nt):
                if len(rule) == 1 and rule[0] in self.info and rule[0] not in flagged \
                        and self.info[rule[0]].node == "-":
                    flagged.add(rule[0])
                    pending.append(rule[0])
        return flagged

    def _layout_only(self, nt):
        """Whether nt, a separator, writes only line breaks and separators."""
        pending, seen = [nt], set()
        while pending:
            cur = pending.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for rule in self._live(cur):
                for sym in rule:
                    if is_nonterminal(sym):
                        if not sym.startswith("__"):
                            return False
                        pending.append(sym)
                    elif sym not in LAYOUT and sym[1:-1] not in SEPARATORS:
                        return False
        return True

    def _quiet(self):
        """(quiet, marked): whether each symbol can derive tokens that print
        nothing, and whether it can do so holding punctuation other than a
        separator."""
        def terminal(sym):
            if sym in LAYOUT or (sym[:1] in "\"'" and sym[1:-1] in SEPARATORS):
                return True, False
            if sym[:1] in "\"'" and sym[1:-1] in PUNCTUATION:
                return True, True
            return False, False

        quiet, marked = {}, {}
        changed = True
        while changed:
            changed = False
            for nt, rules in self.prods.items():
                real = self.real(nt)
                if real in self.info and self.info[real].node != "-" and not nt.startswith("__"):
                    continue
                q, m = quiet.get(nt, False), marked.get(nt, False)
                for rule in rules:
                    if NEVER in rule:
                        continue
                    parts = [terminal(s) if not is_nonterminal(s)
                             else (quiet.get(s, False), marked.get(s, False)) for s in rule]
                    if all(x for x, _ in parts):
                        q = True
                        m = m or any(y for _, y in parts)
                if (q, m) != (quiet.get(nt, False), marked.get(nt, False)):
                    quiet[nt], marked[nt] = q, m
                    changed = True
        return quiet, marked

    def _skeleton(self, rule, quiet):
        """What a rule always prints: its items that cannot be absent or quiet."""
        out = []
        for sym in rule:
            if is_nonterminal(sym):
                if sym.startswith("__rep") and () in self.prods[sym]:
                    continue
                if not quiet.get(sym, False) or sym in self.info:
                    out.append(sym)
            elif sym not in LAYOUT and sym[1:-1] not in PUNCTUATION:
                out.append(sym)
        return tuple(out)


# Tokens ---------------------------------------------------------------------

# The token kinds a grammar terminal of the same name matches; every other
# token matches its quoted spelling.
KIND_TERMINALS = ("IDENT", "INT", "FLOAT", "STRING", "INTERP_STRING", "DOLLAR_PARAM",
                  "NEWLINE", "EOF")


SHIFT_HALF = {"SHL": '"<"', "SHR": '">"'}
# Pseudo-terminals, never written in the grammar: a `<` or `>` directly after
# one of its own kind, with nothing between them.
SHIFT_SECOND = {"SHL": "SHL_SECOND", "SHR": "SHR_SECOND"}
SECOND_OF = {"LT": "SHL_SECOND", "GT": "SHR_SECOND"}


def adjacent(a, b):
    return a.line == b.line and b.column == a.column + len(a.value)


def chart_terms(tokens):
    """Each token's terminals, the shift halves included."""
    terms = [token_terms(t) for t in tokens]
    for k in range(1, len(tokens)):
        a, b = tokens[k - 1], tokens[k]
        if b.kind in SECOND_OF and a.kind == b.kind and (
                adjacent(a, b) or not applies("syntax.lex.shift-adjacent")):
            terms[k].add(SECOND_OF[b.kind])
    return terms


def token_terms(tok):
    """The set of grammar terminals this token satisfies."""
    terms = set()
    if tok.kind in KIND_TERMINALS:
        terms.add(tok.kind)
    if tok.kind == "IDENT":
        terms.add("'" + tok.value + "'")
    elif tok.kind == "HASH_DIRECTIVE":
        terms.add('"#' + tok.value + '"')
    elif tok.kind not in KIND_TERMINALS:
        terms.add('"' + tok.value + '"')
    if tok.kind not in ("LBRACE", "RBRACE", "EOF"):
        terms.add("NON_BRACE")
    return terms


_GENERIC_INNER = {
    "IDENT", "COMMA", "DOT", "NEWLINE", "QUESTION", "DOUBLE_QUESTION", "AMPERSAND",
    "VAR", "INT", "COLON", "LPAREN", "RPAREN", "LBRACKET", "RBRACKET", "SEMICOLON",
    "ARROW", "UNSAFE", "BORROWS", "ASSIGN", "MINUS", "PLUS", "STAR", "SLASH", "PERCENT",
    "LT", "GT",
}


# What a generic list reads as: arguments after a type's path, a layout query's
# word or an expression's name, and parameters after a declaration's name.
LIST_STARTS = ("generic-args", "generic-params")


# What a `<` after a prefix opens, by `list_kind`.
COMMITTED = "committed"
CAST_LIST = "cast"


def list_kind(g, start, prefix):
    """What a `<` after `prefix` opens: CAST_LIST when some reading ends a cast
    target at the `<`, so that it may compare the cast instead; COMMITTED when
    every reading takes it in a type, a declaration head or a layout query,
    never after an expression's name; otherwise None
    (syntax.rule.generic-or-less).

    The chart decides where a `:` or `->` leads a type, so a label's `:` in an
    argument, a field initializer, a payload, a map entry or a named tuple does
    not (syntax.rule.generic-close-split).
    """
    chart = Chart(g, start, prefix)
    hosts = set()
    for nt, ai, dot, _ in chart.frontier:
        alt = g.prods[nt][ai]
        if dot < len(alt) and alt[dot] in LIST_STARTS:
            hosts.add(g.owner[nt][0] if nt.startswith("__") else nt)
    if not hosts:
        return None
    if applies("syntax.rule.generic-or-less") and any(
            nt == CAST_TARGET and len(prefix) in ends for (nt, _), ends in chart.ends.items()):
        return CAST_LIST
    return COMMITTED if hosts.isdisjoint(GENERIC_HOSTS) else None


def cast_follows(g, terms):
    """Whether a token with these terminals can come after a cast target's
    generic list: it continues the target or follows the cast expression, by
    the FOLLOW set the productions give (syntax.rule.generic-or-less). The end
    of a text that stops short of EOF, `terms` None, qualifies too."""
    return terms is None or not terms.isdisjoint(g.cast_list_follow)


def generic_close(tokens, i):
    """(j, closes, newlines) for the `<` at i: the token j holding the `>` that
    closes it, how many lists the leading `>`s of a `>=` or `>>=` at j close (0
    for a plain `>`), and the NEWLINEs between; (None, 0, []) when a token no
    generic list holds comes first."""
    depth = 0
    inside = []
    for j in range(i, len(tokens)):
        t = tokens[j].kind
        if t == "LT":
            depth += 1
        elif t == "GT":
            depth -= 1
            if depth == 0:
                return j, 0, inside
        elif t in ("GTE", "SHR_ASSIGN"):
            closes = 1 if t == "GTE" else 2
            return (j, closes, inside) if depth == closes else (None, 0, [])
        elif t == "NEWLINE":
            inside.append(j)
        elif t not in _GENERIC_INNER:
            break
    return None, 0, []


def matching_close(tokens, i):
    """The index of the bracket closing the `(`, `[` or `{` at i, or None."""
    opener = tokens[i].kind
    closer = {"LPAREN": "RPAREN", "LBRACKET": "RBRACKET", "LBRACE": "RBRACE"}[opener]
    depth = 0
    for j in range(i, len(tokens)):
        if tokens[j].kind == opener:
            depth += 1
        elif tokens[j].kind == closer:
            depth -= 1
            if depth == 0:
                return j
    return None


def generic_lists(g, start, tokens):
    """The tokens with each generic list the parser keeps read whole.

    A list after a name is kept when, read without its line breaks, it parses
    and is followed by `(`, `.` or `{`, or when the parser has committed to it
    (`list_kind`); a cast target's list is kept when it parses as generic
    arguments and the token after it passes `cast_follows`. A kept list drops
    its line breaks (section 2.4 rule 2, syntax.rule.generic-or-less). A list
    whose close is the leading `>` of a `>=` or `>>=` is kept only by those
    last two, and then the token is split (syntax.rule.generic-close-split); so
    `let v: Vector<Int>= w` splits and `f(a: a < b, b: b >= a)` does not.
    Lists are taken left to right, so each `list_kind` chart reads a prefix
    already prepared.
    """
    out = list(tokens)
    i = 1
    while i < len(out):
        if out[i].kind != "LT" or out[i - 1].kind != "IDENT":
            i += 1
            continue
        close, closes, inside = generic_close(out, i)
        if close is None or not (inside or closes) \
                or (closes and not applies("syntax.rule.generic-close-split")):
            i += 1
            continue
        tc = out[close]
        parts = [Token("GT", ">", tc.line, tc.column + k) for k in range(closes)]
        parts.append(Token("ASSIGN", "=", tc.line, tc.column + closes))
        span = [t for t in out[i:close] if t.kind != "NEWLINE"]
        span += parts[:closes] if closes else [tc]
        follow = parts[closes] if closes else (out[close + 1] if close + 1 < len(out) else None)
        if keeps(g, start, out[:i], span, follow):
            if closes:
                out[close:close + 1] = parts
            for k in reversed(inside):
                del out[k]
        i += 1
    return out


def keeps(g, start, prefix, span, follow):
    """Whether the list `span`, a `<` after `prefix` followed by the token
    `follow` (None at the end), is kept; see `generic_lists`."""
    parses = [s for s in LIST_STARTS if Chart(g, s, span).accepted]
    if not parses:
        return False
    after = follow.value if follow is not None else None
    kind = list_kind(g, start, prefix)
    if kind == CAST_LIST:
        return "generic-args" in parses \
            and cast_follows(g, None if follow is None else token_terms(follow))
    return after in GENERIC_FOLLOW or kind == COMMITTED


def bracket_newlines(tokens):
    """The tokens without the NEWLINEs inside `(` `)` and `[` `]` (section 2.4
    rule 1)."""
    out = []
    stack = []
    for tok in tokens:
        if tok.kind == "NEWLINE":
            if stack and stack[-1] in ("LPAREN", "LBRACKET"):
                continue
        elif tok.kind in ("LPAREN", "LBRACKET", "LBRACE"):
            stack.append(tok.kind)
        elif tok.kind in ("RPAREN", "RBRACKET", "RBRACE"):
            if stack:
                stack.pop()
        out.append(tok)
    return out


def prepare(g, tokens, start="source-file"):
    """The token stream the grammar reads from `start`: the NEWLINEs section 2.4
    makes insignificant removed, and generic closes split. Rule 1 comes first,
    so the chart behind a committed list reads a prefix it can parse."""
    return generic_lists(g, start, bracket_newlines(tokens))


def non_ascii_identifier(tokens):
    """The first identifier with a non-ASCII character (syntax.lex.ascii-identifier)."""
    for t in tokens:
        if t.kind == "IDENT" and not t.value.isascii():
            return t
    return None


# Earley ---------------------------------------------------------------------

class Chart:
    """One Earley pass: whether `start` spans the input, how far it got,
    `ends[(nt, i)]`, the positions where a completed `nt` from `i` ends, and
    `frontier`, the items at the end of the input, which say what a prefix's
    readings take next."""

    def __init__(self, g, start, tokens):
        self.g = g
        self.start = start
        self.tokens = tokens
        self.terms = chart_terms(tokens)
        self.accepted, self.furthest, self.ends, self.frontier = self._run()

    def _run(self):
        g, n = self.g, len(self.tokens)
        items = [set() for _ in range(n + 1)]
        agenda = [[] for _ in range(n + 1)]
        waiting = [dict() for _ in range(n + 1)]
        done = [dict() for _ in range(n + 1)]
        terms = self.terms

        def add(i, item):
            if item not in items[i]:
                items[i].add(item)
                agenda[i].append(item)

        for ai in range(len(g.prods[self.start])):
            add(0, (self.start, ai, 0, 0))
        furthest = 0
        for i in range(n + 1):
            k = 0
            while k < len(agenda[i]):
                item = agenda[i][k]
                nt, ai, dot, origin = item
                k += 1
                alt = g.prods[nt][ai]
                if dot < len(alt):
                    sym = alt[dot]
                    if is_nonterminal(sym):
                        if sym == NEVER:
                            continue
                        waiting[i].setdefault(sym, []).append(item)
                        for bj in range(len(g.prods[sym])):
                            add(i, (sym, bj, 0, i))
                        # Nullable symbols, and completions made before this wait.
                        if sym in g.nullable or i in done[i].get(sym, ()):
                            add(i, (nt, ai, dot + 1, origin))
                    elif i < n and sym in terms[i]:
                        add(i + 1, (nt, ai, dot + 1, origin))
                        furthest = max(furthest, i + 1)
                else:
                    done[i].setdefault(nt, set()).add(origin)
                    for (pnt, pai, pdot, porigin) in list(waiting[origin].get(nt, ())):
                        add(i, (pnt, pai, pdot + 1, porigin))
        ends = {}
        for j in range(n + 1):
            for nt, origins in done[j].items():
                for o in origins:
                    ends.setdefault((nt, o), set()).add(j)
        accepted = n in ends.get((self.start, 0), ())
        return accepted, furthest, ends, items[n]


# Trees ----------------------------------------------------------------------

class Derivation:
    """One derivation of nonterminal `nt` by rule `ai` over tokens [i, j).

    `kids` holds a Derivation per nonterminal and a token index per terminal;
    `tree` is the node it builds (tuples: ("node", kind, kids), ("tok", text),
    ("splice", kids) for a production that builds no node of its own).
    """
    __slots__ = ("nt", "ai", "i", "j", "kids", "tree")

    def __init__(self, nt, ai, i, j, kids, tree):
        self.nt, self.ai, self.i, self.j, self.kids, self.tree = nt, ai, i, j, kids, tree


def is_tok(c):
    return isinstance(c, tuple) and c[0] == "tok"


class Forest:
    """Every distinct tree the chart holds for a span, up to TREE_CAP per span.

    Building a span records the rules that refused a derivation of it, and the
    spans inside it that turned out to have no tree, so `refusal` can name the
    rule behind a text no tree survives.
    """

    def __init__(self, chart):
        self.c = chart
        self.memo = {}
        self.active = set()
        self.building = []
        self.refused = collections.defaultdict(set)
        self.dead = collections.defaultdict(set)
        self.filters = collections.defaultdict(list)
        for nt, method, rule in FILTERS:
            if applies(rule):
                self.filters[nt].append((getattr(self, method), rule))

    def derivations(self, nt, i, j):
        key = (nt, i, j)
        if key in self.memo:
            return self.memo[key]
        if key in self.active:
            return []
        self.active.add(key)
        self.building.append(key)
        out = []
        for ai, alt in enumerate(self.c.g.prods[nt]):
            for kids in self._seq(alt, 0, i, j):
                tree = self._build(nt, ai, [k[0] for k in kids])
                d = Derivation(nt, ai, i, j, tuple(k[1] for k in kids), tree)
                # A refused derivation is dropped before it counts against the cap.
                why = self._refusal(d)
                if why is not None:
                    self.refused[key].add(why)
                    continue
                out.append(d)
                if len(out) >= TREE_CAP:
                    break
        self.building.pop()
        self.active.discard(key)
        if nt in PREFERENCES and any(applies(r) for r in PREFERENCES[nt][1]):
            preferred = PREFERENCES[nt][0]
            kept = [d for d in out
                    if self.c.g.alternative(nt, d.ai).effective_name == preferred]
            out = kept or out
        uniq = []
        seen = set()
        for d in out:
            if d.tree not in seen:
                seen.add(d.tree)
                uniq.append(d)
        self.memo[key] = uniq
        return uniq

    def _real_kids(self, d):
        out = []
        for k in d.kids:
            if isinstance(k, int):
                out.append(k)
            elif k.nt.startswith("__"):
                out.extend(self._real_kids(k))
            else:
                out.append(k)
        return out

    def refusal(self, key):
        """(token index, rule) behind a span with no tree, or None when no rule
        refused anything on the way to it. Every reading of the span failed, so
        each refusal under it explains one; like the chart's own error, the
        report is the reading that got furthest."""
        found = set()
        seen = {key}
        pending = [key]
        while pending:
            cur = pending.pop()
            if self.memo.get(cur):
                continue
            found |= self.refused.get(cur, set())
            for child in self.dead.get(cur, ()):
                if child not in seen:
                    seen.add(child)
                    pending.append(child)
        return max(found) if found else None

    def _refusal(self, d):
        for stands, rule in self.filters.get(d.nt, ()):
            at = stands(d)
            if at is not None:
                return at, rule
        return None

    # Helpers over one derivation --------------------------------------------

    def _alt(self, d):
        return self.c.g.alternative(d.nt, d.ai).effective_name

    def _token(self, k):
        """The token at index k, or None past the end of the input."""
        return self.c.tokens[k] if k < len(self.c.tokens) else None

    def _after(self, d):
        """The spelling of the token after d, or None at the end of the input."""
        t = self._token(d.j)
        return None if t is None else t.value

    def _kids_named(self, d, nt):
        return [k for k in self._real_kids(d) if not isinstance(k, int) and k.nt == nt]

    def _descendants(self, d, nt):
        """Every derivation of nt under d, in source order."""
        out = []
        for k in self._real_kids(d):
            if isinstance(k, int):
                continue
            if k.nt == nt:
                out.append(k)
            else:
                out.extend(self._descendants(k, nt))
        return out

    def _word(self, d, word):
        """The index of the token spelled `word` among d's own tokens, or None."""
        for k in self._real_kids(d):
            if isinstance(k, int) and self.c.tokens[k].value == word:
                return k
        return None

    def _params(self, d):
        """The params of a declaration, in order."""
        lists = self._kids_named(d, "param-list")
        return self._kids_named(lists[0], "param") if lists else []

    def _hop(self, hop):
        """(kind, leaf derivation) of one hop: `member` for a member or optional
        member, `call`, `call-trailing` for a call with a trailing closure,
        `trailing`, or `other`."""
        while hop.nt not in LEAF_HOPS and len(hop.kids) == 1 \
                and isinstance(hop.kids[0], Derivation):
            hop = hop.kids[0]
        kind = LEAF_HOPS.get(hop.nt, "other")
        if kind == "call" and self._alt(hop) == "syntax.expr.call.paren-trailing":
            kind = "call-trailing"
        return kind, hop

    def _closure_start(self, hop):
        """The `{` of the trailing closure a trailing or call-trailing hop holds."""
        return self._kids_named(hop, "closure-literal")[-1].i

    def _has_generic_args(self, d):
        return bool(self._kids_named(d, "generic-args"))

    # Filters: None when the derivation stands, else the token it is refused at.

    def _generic_or_less(self, d):
        """A `<` after a name compares only when no generic list from it parses
        and is followed by `(`, `.` or `{`, or after a cast target by a token
        `_cast_list_follows` takes (syntax.rule.generic-or-less)."""
        toks = self.c.tokens
        kids = self._real_kids(d)
        for n, k in enumerate(kids):
            if isinstance(k, int) or k.nt != "compare-op":
                continue
            p = k.kids[0]
            if toks[p].value != "<" or p == 0 or toks[p - 1].kind != "IDENT":
                continue
            cast = any(t.j == p for t in self._descendants(kids[n - 1], CAST_TARGET))
            follows = self._cast_list_follows if cast else self._name_list_follows
            if any(follows(e) for e in self.c.ends.get(("generic-args", p), ())):
                return p
        return None

    def _name_list_follows(self, e):
        return e < len(self.c.tokens) and self.c.tokens[e].value in GENERIC_FOLLOW

    def _cast_list_follows(self, e):
        return cast_follows(self.c.g, self.c.terms[e] if e < len(self.c.tokens) else None)

    def _cast_list(self, d):
        """A generic list after a complete cast target stands only when the
        token after it can follow there (syntax.rule.generic-or-less)."""
        complete = self.c.ends.get((CAST_TARGET, d.i), ())
        for k in self._descendants(d, "generic-args"):
            if k.i in complete and not self._cast_list_follows(k.j):
                return k.i
        return None

    def _generic_kept(self, d):
        """In an expression, a generic list after a name or member stands only
        when `(`, `.` or `{` follows it (syntax.rule.generic-or-less)."""
        if self._has_generic_args(d) and self._after(d) not in GENERIC_FOLLOW:
            return self._kids_named(d, "generic-args")[0].i
        return None

    def _trailing_closure(self, d):
        """A trailing closure attaches only to a name, member or implicit-member
        callee, and at most once (syntax.rule.trailing-closure)."""
        kids = [k for k in self._real_kids(d) if not isinstance(k, int)]
        callee = self._alt(kids[0]) in TRAILING_CALLEES
        for hop in kids[1:]:
            kind, leaf = self._hop(hop)
            if kind in ("trailing", "call-trailing") and not callee:
                return self._closure_start(leaf)
            callee = kind == "member"
        return None

    def _head_restriction(self, d):
        """No trailing closure at a head's outer level, and no generic list kept
        by the `{` that begins the body (syntax.rule.head-restriction)."""
        pending = [d]
        while pending:
            cur = pending.pop()
            for k in cur.kids:
                if isinstance(k, int):
                    continue
                if k.nt in HEAD_RESETS and applies("syntax.rule.head-reset"):
                    continue
                if k.nt in LEAF_HOPS:
                    kind, _ = self._hop(k)
                    if kind in ("trailing", "call-trailing"):
                        return self._closure_start(k)
                if k.nt in GENERIC_HOSTS and self._has_generic_args(k) \
                        and self._after(k) == "{":
                    return k.j
                pending.append(k)
        return None

    def _borrow_form(self, d):
        """`borrow let` or `borrow var` and a name or a parenthesized pattern
        followed by `=` is a binding, never the place form (syntax.rule.borrow-form)."""
        if self._after(d) != "=":
            return None
        toks = self.c.tokens
        first, last = d.i + 2, d.j - 1
        if first == last and toks[first].kind == "IDENT":
            return d.i
        if toks[first].value == "(" and toks[last].value == ")" \
                and matching_close(toks, first) == last:
            return d.i
        return None

    def _try_block(self, d):
        """`try` directly followed by `{` is a try block (syntax.rule.try-block)."""
        k = d.i + 1
        while k < d.j and self.c.tokens[k].kind == "NEWLINE":
            k += 1
        return k if self.c.tokens[k].value == "{" else None

    def _lends_word(self, d):
        """`lends` is the operator only before `self` or a name
        (syntax.rule.contextual-words)."""
        t = self.c.tokens[d.i + 1]
        return None if t.kind == "IDENT" or t.value == "self" else d.i

    def _static_assert_word(self, d):
        """A statement that starts `static_assert (` is the assertion, never a
        call, and so is an arm body, which means what the same statement in
        braces means (syntax.rule.contextual-words, syntax.rule.arm-body)."""
        toks = self.c.tokens
        if self._alt(d) in EXPRESSION_STATEMENTS and toks[d.i].value == "static_assert" \
                and toks[d.i].kind == "IDENT" and toks[d.i + 1].value == "(":
            return d.i
        return None

    def _arm_body(self, d):
        """An arm body that starts with `{` is a block (syntax.rule.arm-body)."""
        if self._alt(d) != "syntax.expr.arm-body.block" and self.c.tokens[d.i].value == "{":
            return d.i
        return None

    def _cast_question(self, d):
        """No `??` after a cast target, and no second `?` after its own
        (syntax.rule.cast-target-question)."""
        if self._alt(d) != "syntax.expr.cast-suffix.cast":
            return None
        after = self._after(d)
        target = self._kids_named(d, "cast-target")[0]
        if after == "??" or (after == "?"
                             and self._alt(target) == "syntax.type.cast-target.optional"):
            return d.j
        return None

    def _range_open_end(self, d):
        """A range omits its upper bound only before a closing token, a
        separator, a line break or the end of input (syntax.rule.range-open-end)."""
        if d.nt == "range-upto" and self._alt(d) != "syntax.expr.range-upto.full":
            return None
        t = self._token(d.j)
        if t is None or t.kind in ("NEWLINE", "EOF") \
                or t.value in OPEN_END_FOLLOW:
            return None
        return d.j

    def _discard_binding(self, d):
        """`var _ = e` is the refused form, never a binding
        (syntax.rule.discard-binding)."""
        if self._alt(d) != "syntax.stmt.let.mutable":
            return None
        name = self._kids_named(d, "binding-name")[0]
        return name.i if self.c.tokens[name.i].value == "_" else None

    def _extern_abi(self, d):
        """The ABI string is "C" (syntax.rule.extern-abi)."""
        return None if self.c.tokens[d.i + 1].value == "C" else d.i + 1

    def _attribute_position(self, d):
        """Each attribute on a declaration it may stand on, once
        (syntax.rule.attribute-position)."""
        allowed = ATTRIBUTE_HOSTS.get(self._alt(d))
        lists = self._kids_named(d, "attribute-list")
        if allowed is None or not lists:
            return None
        seen = set()
        for attr in self._kids_named(lists[0], "attribute"):
            name = ATTRIBUTE_NAMES[self._alt(attr)]
            if name not in allowed or name in seen:
                return attr.i
            seen.add(name)
        return None

    def _receiver_and_static(self, d):
        """A receiver only as a method's first parameter; a method or
        requirement has one exactly when it is not `static`
        (syntax.rule.receiver-and-static)."""
        params = self._params(d)
        receivers = [params[n].i for n, p in enumerate(params) if self._alt(p) in RECEIVERS]
        if d.nt in ("func-decl", "init-decl") or self.c.tokens[d.i].value == "static":
            return receivers[0] if receivers else None
        if not receivers:
            return d.i
        misplaced = [at for at in receivers if at != params[0].i]
        return misplaced[0] if misplaced else None

    def _effect_placement(self, d):
        """`consumes` only on a method with a `&var self` receiver, and no
        `borrows` on `init` (syntax.rule.effect-slot)."""
        slot = self._kids_named(d, "effect-slot")[0]
        consumes = self._word(slot, "consumes")
        if d.nt == "init-decl" and self._kids_named(slot, "borrows-effect"):
            return self._kids_named(slot, "borrows-effect")[0].i
        if consumes is None:
            return None
        params = self._params(d)
        if d.nt == "method-decl" and params and self._exclusive_receiver(params[0]):
            return None
        return consumes

    def _exclusive_receiver(self, param):
        receivers = self._kids_named(param, "receiver")
        return bool(receivers) and self._alt(receivers[0]) == "syntax.decl.receiver.exclusive"

    def _requirement_consumes(self, d):
        """A trait requirement is never `consumes` (syntax.rule.requirement-borrows)."""
        return self._word(self._kids_named(d, "effect-slot")[0], "consumes")

    def _try_route_case(self, d):
        """A routing clause names an enum and a case (syntax.rule.try-route-case)."""
        path = self._kids_named(d, "path")[0]
        names = [k for k in self._real_kids(path)
                 if isinstance(k, int) and self.c.tokens[k].kind == "IDENT"]
        return path.i if len(names) < 2 else None

    def _import_names(self, d):
        """A selective import binds each local name once (syntax.rule.import-names)."""
        seen = set()
        for symbol in self._descendants(d, "import-symbol"):
            names = [k for k in self._real_kids(symbol)
                     if isinstance(k, int) and self.c.tokens[k].kind == "IDENT"]
            local = self.c.tokens[names[-1]].value
            if local in seen:
                return symbol.i
            seen.add(local)
        return None

    def _continues(self, alt, k, pos, j):
        """Whether the symbols of alt from k can take the next token at pos,
        looking past those that can only be empty there."""
        while k < len(alt):
            sym = alt[k]
            if not is_nonterminal(sym):
                return pos < j and sym in self.c.terms[pos]
            ends = [e for e in self.c.ends.get((sym, pos), ()) if e <= j]
            if any(e > pos for e in ends):
                return True
            if pos not in ends:
                return False
            k += 1
        return pos == j

    def _seq(self, alt, k, pos, j):
        if k == len(alt):
            if pos == j:
                yield []
            return
        sym = alt[k]
        if not is_nonterminal(sym):
            if pos < j and sym in self.c.terms[pos]:
                for rest in self._seq(alt, k + 1, pos + 1, j):
                    yield [(("rawtok", self.c.tokens[pos].value, pos), pos)] + rest
            return
        for e in sorted(self.c.ends.get((sym, pos), ())):
            if e > j:
                continue
            subs = self.derivations(sym, pos, e)
            if not subs:
                # Only a span the rest of the sequence could follow explains
                # a refusal; the others fail at the chart's level anyway.
                if self._continues(alt, k + 1, e, j):
                    self.dead[self.building[-1]].add((sym, pos, e))
                continue
            for rest in self._seq(alt, k + 1, e, j):
                for s in subs:
                    yield [(s.tree, s)] + rest

    def _build(self, nt, ai, kids):
        """The node a derivation builds from its kids' (section 1, Nodes).

        A `node=-` production passes its kids on; a production that names a
        node builds it, except that a chain alternative with one operand passes
        the operand on. Hop chains nest one node per hop
        (syntax.rule.postfix-per-hop): the postfix chains, the assignment
        targets, a `move` operand's place path and a run of casts; each run of
        an optional chain in them is an OptionalChain node (`nest`).
        """
        g = self.c.g
        alt = g.prods[nt][ai]
        flat = []
        for k, kid in enumerate(kids):
            if kid[0] == "rawtok":
                flat.append(("tok", kid[1], kid[2], g.shown(nt, alt[k])))
            elif kid[0] == "splice":
                flat.extend(kid[1])
            else:
                flat.append(kid)
        if nt.startswith("__"):
            if nt.startswith(SHIFT_AUX):
                # The two halves of a shift are one operator.
                first = flat[0]
                return ("splice", (("tok", first[1] * 2, first[2], True),))
            return ("splice", tuple(flat))
        p = g.info[nt]
        name, node = p.name, p.node
        if name in SUFFIXED and flat and not is_tok(flat[0]):
            # Each `?` wraps the type once and a `??` twice (section 5), so a
            # layer is an OptionalType node whatever token wrote it.
            base = flat[0]
            for c in flat[1:]:
                mark = c[1] if is_tok(c) else c[2][0][1]
                for _ in range(len(mark)):
                    base = ("node", OPTIONAL_TYPE, (base,), "")
            return base
        if nt in HOP_CHAINS and flat:
            return nest(flat, g.run_opens, g.run_closes)
        if nt == REFUSAL_BODY:
            flat = self._shifts_joined(flat)
        nodes = [c for c in flat if not is_tok(c)]
        toks = [c for c in flat if is_tok(c)]
        if node == "-":
            # A group's parentheses, and the end of input after a segment's
            # expression, hold nothing the node lacks; parentheses a flagged
            # production shows are leaves, and stay.
            if len(nodes) == 1 and all(t[1] in ("(", ")", "") and not t[3] for t in toks):
                return nodes[0]
            return ("splice", tuple(flat))
        if node in CHAINS and g.chain_alternative(nt, ai) and len(nodes) == 1 and not toks:
            return nodes[0]
        suffix = g.suffix(nt, ai)
        if nt == "cast-expr":
            return cast_chain(flat)
        if nt == "move-expr" and suffix == "place":
            chain = nest(nodes)
            return ("node", node, tuple([toks[0], chain] + toks[1:]), suffix)
        return ("node", node, tuple(flat), suffix)

    def _shifts_joined(self, flat):
        """A refusal body's tokens, each `<` or `>` touching one of its own kind
        joined with it into one leaf: no production reads the body, so the leaf
        keeps the adjacency syntax.lex.shift-adjacent decides by."""
        out = []
        for c in flat:
            prev = out[-1] if out else None
            if prev is not None and is_tok(c) and is_tok(prev) and c[1] in ("<", ">") \
                    and prev[1] == c[1] and adjacent(self.c.tokens[prev[2]], self.c.tokens[c[2]]):
                out[-1] = ("tok", c[1] * 2, prev[2], True)
                continue
            out.append(c)
        return out


# Hop chains written as a base and its hops, whose nodes nest one per hop.
HOP_CHAINS = ("postfix-expr", "projection-target", "call-target", "optional-chain-target")
SHIFT_AUX = ("__shl", "__shr")
REFUSAL_BODY = "refusal-body"
# The hops that open a run of an optional chain, and those that close an open
# one; the end of the chain closes it too (syntax.rule.optional-chain-run).
RUN_OPENS = ("syntax.expr.optional-member",)
RUN_CLOSES = ("syntax.expr.tuple-index", "syntax.expr.subscript", "syntax.expr.force")
OPTIONAL_CHAIN = "OptionalChain"


def nest(items, opens=(), closes=()):
    """The base node, wrapped by each hop node after it in turn, and each run
    of an optional chain, from the base to the hop before the one that closes
    it, wrapped in one OptionalChain node. `opens` and `closes` are the Kinds of
    the hops that open and close a run."""
    base = items[0]
    running = False
    for hop in items[1:]:
        if is_tok(hop):
            continue
        if running and hop[1] in closes:
            base = ("node", OPTIONAL_CHAIN, (base,), "")
            running = False
        base = ("node", hop[1], (base,) + hop[2], hop[3])
        running = running or hop[1] in opens
    if running:
        base = ("node", OPTIONAL_CHAIN, (base,), "")
    return base


def cast_chain(flat):
    """A cast chain nested one `Cast` per `as`: the operand, then each hop's `as`
    and target."""
    base = flat[0]
    hop = []
    for c in flat[1:] + [None]:
        if c is None or (is_tok(c) and c[1] == "as" and hop):
            base = ("node", "Cast", (base,) + tuple(hop), "")
            hop = []
        if c is not None:
            hop.append(c)
    return base


class Record:
    """The coverage data of one tree (see the module docstring)."""

    def __init__(self):
        self.alternatives = collections.Counter()
        self.cells = []

    def to_json(self):
        return {"alternatives": dict(sorted(self.alternatives.items())),
                "cells": [list(c) for c in self.cells]}

    def lines(self):
        """The record as text: each cell in tree order, then each alternative."""
        out = ["cell %s %s%s %s" % (c, ctx, " paren" if paren else "", pos)
               for c, ctx, paren, pos in self.cells]
        out += ["alternative %s %d" % (name, n) for name, n in sorted(self.alternatives.items())]
        return out


class Parse:
    """The result of parsing one token stream from one start symbol."""

    def __init__(self, g, start, tokens):
        self.g = g
        self.start = start
        self.tokens = tokens
        self.chart = Chart(g, start, tokens)
        self._derivations = None
        self._forest = None

    @property
    def accepted(self):
        return self.chart.accepted

    def derivations(self):
        """One derivation per distinct tree, in a fixed order."""
        if self._derivations is None:
            if not self.accepted:
                self._derivations = []
            else:
                self._forest = Forest(self.chart)
                self._derivations = self._forest.derivations(self.start, 0, len(self.tokens))
        return self._derivations

    def refusal(self):
        """"L:C refused by RULE" for a text the chart accepts and the rules
        leave no tree, or None when no rule refused anything on the way."""
        if self.derivations() or self._forest is None:
            return None
        why = self._forest.refusal((self.start, 0, len(self.tokens)))
        if why is None:
            return None
        at, rule = why
        t = self.tokens[min(at, len(self.tokens) - 1)]
        return "%d:%d refused by %s" % (t.line, t.column, rule)

    def documented(self, derivation):
        """The token indices where a declaration a `///` run may document starts.
        `@test` before a declaration stands where its attributes do, so the run
        may come before it (syntax.rule.test-form)."""
        out = set()
        for d in walk_real(self.g, derivation):
            name = self.g.alternative(d.nt, d.ai).effective_name
            if name in DOCUMENTED:
                out.add(d.i)
            elif name == TEST_ONLY_DECLARATION:
                item = [k for k in d.kids if isinstance(k, Derivation)
                        and k.nt == "declaration-item"]
                if item and self.g.alternative(item[0].nt, item[0].ai).effective_name \
                        in DOCUMENTED:
                    out.add(d.i)
        return out

    def trees(self):
        return [d.tree for d in self.derivations()]

    def record(self, derivation, root_context=None):
        rec = Record()
        for d in walk_real(self.g, derivation):
            rec.alternatives[self.g.alternative(d.nt, d.ai).effective_name] += 1
        rec.cells = contexts.cells(self, derivation, root_context)
        return rec


def walk_real(g, d):
    """Every derivation of a real (non-auxiliary) nonterminal under d, preorder."""
    stack = [d]
    while stack:
        cur = stack.pop()
        if not cur.nt.startswith("__"):
            yield cur
        stack.extend(k for k in reversed(cur.kids) if isinstance(k, Derivation))


# Files ----------------------------------------------------------------------

def lex(text):
    """(tokens, None) or (None, the lex error)."""
    tokens, _, err = lex_with_docs(text)
    return tokens, err


def lex_with_docs(text=None, path=None):
    """(tokens, doc comments, None) or (None, None, the lex error) for a text, or
    for the file at `path`."""
    try:
        tokens, docs = lexdump.lex_file(path) if path is not None else lexdump.lex_text(text)
    except lexdump.LexError as e:
        return None, None, e
    return tokens, docs, None


def lex_error_detail(err):
    return "Lexer error at %d:%d: %s" % (err.line, err.column, err.message)


def doc_runs(docs):
    """[(first line, first column, last line)] for each run of `///` lines."""
    runs = []
    for dc in docs:
        if dc.kind != "doc":
            continue
        if runs and dc.line == runs[-1][2] + 1:
            runs[-1] = (runs[-1][0], runs[-1][1], dc.line)
        else:
            runs.append((dc.line, dc.column, dc.line))
    return runs


def module_doc_error(tokens, docs):
    """"L:C ..." for a `//!` line after the first token (syntax.lex.module-doc)."""
    first = next((t for t in tokens if t.kind not in ("NEWLINE", "EOF")), None)
    for dc in docs:
        if dc.kind == "module" and first is not None and dc.line > first.line \
                and applies("syntax.lex.module-doc"):
            return "%d:%d refused by syntax.lex.module-doc" % (dc.line, dc.column)
    return None


def doc_attach_error(parse, derivation, docs):
    """"L:C ..." for a `///` run that documents nothing (syntax.lex.doc-attach)."""
    if not applies("syntax.lex.doc-attach"):
        return None
    starts = None
    for line, column, last in doc_runs(docs):
        after = next((k for k, t in enumerate(parse.tokens)
                      if t.line > last and t.kind != "NEWLINE"), None)
        if starts is None:
            starts = parse.documented(derivation)
        if after is None or after not in starts:
            return "%d:%d refused by syntax.lex.doc-attach" % (line, column)
    return None


def check_source(g, src, trees=False, path=None):
    """(verdict, detail) for one source text, read from `path` when it is given.

    OK; LEXERR, a lex error, a non-ASCII identifier or a misplaced `//!`; FAIL,
    the chart refuses the tokens (detail: the furthest token reached), or the
    rules leave no tree (detail: the rule and where it refused); SEGLEX or
    SEGFAIL, an interpolation segment fails to lex or to parse. NOTREE is a
    finding: no tree, and no rule refused anything. With `trees`, a text whose
    tree, or a segment's, is not unique after the rules is AMBIGUOUS.
    """
    checked = check(g, src, trees, path)
    return checked.verdict, checked.detail


class Checked:
    """One text's verdict and detail (check_source), its doc comments, and the
    parses behind an OK verdict: (origin, Parse) for the file, origin "", and
    each interpolation segment, origin its "line:col" as expression_segments
    gives it."""

    def __init__(self, verdict, detail, parses=(), docs=()):
        self.verdict = verdict
        self.detail = detail
        self.parses = list(parses)
        self.docs = list(docs)


def check(g, src, trees=False, path=None):
    """The Checked result of check_source for one text: every refusal it makes,
    the lexical ones included, is decided here once."""
    toks, docs, err = lex_with_docs(src, path)
    if err is not None:
        return Checked("LEXERR", lex_error_detail(err))
    bad = non_ascii_identifier(toks)
    if bad is not None:
        return Checked("LEXERR", "%d:%d refused by syntax.lex.ascii-identifier: %r"
                       % (bad.line, bad.column, bad.value))
    misplaced = module_doc_error(toks, docs)
    if misplaced is not None:
        return Checked("LEXERR", misplaced)
    toks = prepare(g, toks)
    file_parse = Parse(g, "source-file", toks)
    if not file_parse.accepted:
        t = toks[min(file_parse.chart.furthest, len(toks) - 1)]
        return Checked("FAIL", "%d:%d near %s %r" % (t.line, t.column, t.kind, t.value))
    ds = file_parse.derivations()
    if not ds:
        refused = file_parse.refusal()
        if refused is None:
            return Checked("NOTREE", "no tree, and no rule refused one")
        return Checked("FAIL", refused)
    parses = [("", file_parse)]
    pending = expression_segments(toks, "")
    while pending:
        where, seg = pending.pop(0)
        stoks, err = lex(seg.text)
        if err is not None:
            return Checked("SEGLEX", "%s %s" % (where, lex_error_detail(err)))
        bad = non_ascii_identifier(stoks)
        if bad is not None:
            return Checked("SEGLEX", "%s %d:%d refused by syntax.lex.ascii-identifier: %r"
                           % (where, bad.line, bad.column, bad.value))
        segment = Parse(g, "interp-segment", prepare(g, stoks, "interp-segment"))
        if not segment.accepted:
            return Checked("SEGFAIL", "%s {%s}" % (where, seg.text))
        if not segment.derivations():
            refused = segment.refusal()
            if refused is None:
                return Checked("NOTREE", "segment %s: no tree, and no rule refused one" % where)
            return Checked("SEGFAIL", "%s {%s} %s" % (where, seg.text, refused))
        parses.append((where, segment))
        pending[0:0] = expression_segments(stoks, where + "/")
    if trees:
        for where, parse in parses:
            ds = parse.derivations()
            if len(ds) > 1:
                label = "segment %s: " % where if where else ""
                return Checked("AMBIGUOUS", label + ambiguity_site(parse, ds[0], ds[1]))
    undocumented = doc_attach_error(file_parse, file_parse.derivations()[0], docs)
    if undocumented is not None:
        return Checked("FAIL", undocumented)
    return Checked("OK", "", parses, docs)


def ambiguity_site(parse, a, b):
    """Where two derivations first part: the position, the nonterminal and the
    two alternatives."""
    g = parse.g
    while True:
        diverge = (a.ai != b.ai or (a.i, a.j) != (b.i, b.j) or len(a.kids) != len(b.kids))
        if not diverge:
            pair = None
            for ka, kb in zip(a.kids, b.kids):
                if isinstance(ka, int) or isinstance(kb, int):
                    if ka != kb:
                        diverge = True
                        break
                elif ka.tree != kb.tree or (ka.i, ka.j) != (kb.i, kb.j):
                    if ka.nt == kb.nt:
                        pair = (ka, kb)
                    else:
                        diverge = True
                    break
            if pair is not None and not diverge:
                a, b = pair
                continue
        break

    def label(d):
        nt, ai = (d.nt, d.ai) if not d.nt.startswith("__") else g.owner[d.nt]
        return nt, g.alternative(nt, ai).effective_name

    t = parse.tokens[a.i] if a.i < len(parse.tokens) else parse.tokens[-1]
    (nt, first), (_, second) = label(a), label(b)
    return "%d:%d %s: %s | %s" % (t.line, t.column, nt, first, second)


def source_parses(g, src):
    """(origin, Parse) for a file's text and each interpolation segment in it,
    the segment's origin being its "line:col"; the text must lex."""
    toks, err = lex(src)
    if err is not None:
        raise err
    return segment_parses(g, Parse(g, "source-file", prepare(g, toks)))


def segment_parses(g, file_parse):
    """(origin, Parse) for a parsed file and each interpolation segment in it."""
    toks = file_parse.tokens
    out = [("", file_parse)]
    pending = expression_segments(toks, "")
    while pending:
        where, seg = pending.pop(0)
        stoks = text_tokens(g, seg.text, "interp-segment")
        out.append((where, Parse(g, "interp-segment", stoks)))
        pending[0:0] = expression_segments(stoks, where + "/")
    return out


def expression_segments(tokens, prefix):
    """[("line:col", segment)] for each expression segment of the interpolated
    strings in `tokens`, in order. A nested segment's position is relative to the
    segment around it, so its origin is that segment's, then "/", then its own."""
    return [("%s%d:%d" % (prefix, seg.line, seg.column), seg)
            for tok in tokens if tok.kind == "INTERP_STRING" and tok.segments
            for seg in tok.segments if seg.kind == "expr"]


def check_file(g, path, trees=False):
    return check_source(g, None, trees, path)


def text_tokens(g, text, start):
    """The prepared tokens of TEXT; a start other than source-file drops the
    trailing NEWLINE and EOF, which only source-file and interp-segment take."""
    toks, err = lex(text)
    if err is not None:
        raise err
    toks = prepare(g, toks, start)
    if start not in ("source-file", "interp-segment", "refusal-unit"):
        while toks and toks[-1].kind in ("EOF", "NEWLINE"):
            toks.pop()
    return toks


def check_paths(paths, grammar_path=extract.GRAMMAR, enable=(), jobs=None):
    """[(verdict, detail)] per path, in order, over `jobs` worker processes."""
    if min(jobs or 1, len(paths)) <= 1:
        g = Grammar(extract.extract(grammar_path), enable)
        return [check_file(g, p) for p in paths]
    cmd = [os.path.abspath(__file__), "--worker", "--grammar", grammar_path]
    if enable == "all":
        cmd.append("--removed")
    else:
        for nt in sorted(enable):
            cmd += ["--enable", nt]
    return [tuple(r) for r in run_workers(cmd, paths, jobs)]


def run_workers(script_args, paths, jobs):
    """Each path's JSON result line from `python SCRIPT_ARGS`, which reads paths
    on stdin. Plain subprocesses, since a sandbox may refuse the semaphores
    multiprocessing needs; results come back in the order of `paths`."""
    jobs = max(1, min(jobs, len(paths)))
    # Built here, so that workers never race to build it.
    lexdump.ensure_sawc2()
    cmd = [sys.executable] + list(script_args)

    def work(share):
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        out, _ = proc.communicate("".join(p + "\n" for p in share))
        lines = out.splitlines()
        if proc.returncode != 0 or len(lines) != len(share):
            raise RuntimeError("a grammar worker failed (exit %d, %d of %d results)"
                               % (proc.returncode, len(lines), len(share)))
        return [json.loads(line) for line in lines]

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        shares = list(pool.map(work, [paths[k::jobs] for k in range(jobs)]))
    results = [None] * len(paths)
    for k, share in enumerate(shares):
        for n, result in enumerate(share):
            results[k + n * jobs] = result
    return results


def run_worker(grammar_path, enable):
    g = Grammar(extract.extract(grammar_path), enable)
    for line in sys.stdin:
        sys.stdout.write(json.dumps(check_file(g, line.rstrip("\n"))) + "\n")
    return 0


def default_jobs():
    return min(8, os.cpu_count() or 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--list", metavar="LISTFILE", help="check every path the file lists")
    ap.add_argument("--root", default=".", help="the directory list paths are relative to")
    ap.add_argument("--grammar", default=extract.GRAMMAR)
    ap.add_argument("--removed", action="store_true", help="enable every removed production")
    ap.add_argument("--jobs", type=int, default=default_jobs())
    ap.add_argument("--trees", action="store_true", help="print every tree of each input")
    ap.add_argument("--record", action="store_true", help="with --trees, print each coverage record")
    ap.add_argument("--start", default="source-file", help="with --trees, the start symbol")
    ap.add_argument("--text", help="with --trees, parse this text instead of files")
    ap.add_argument("--enable", action="append", default=[], metavar="NONTERMINAL",
                    help="enable one removed production")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    sys.setrecursionlimit(RECURSION_LIMIT)
    enable = "all" if args.removed else set(args.enable)
    if args.worker:
        return run_worker(args.grammar, enable)
    if args.trees:
        return print_trees(args, enable)
    if args.list:
        with open(args.list, encoding="utf-8") as fh:
            files = [ln.strip() for ln in fh if ln.strip()]
    else:
        files = args.files
    results = check_paths([os.path.join(args.root, f) for f in files], args.grammar,
                          enable, args.jobs)
    counts = {}
    for f, (verdict, info) in zip(files, results):
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict != "OK":
            print("%s\t%s\t%s" % (verdict, f, info))
    print("summary:", counts, "files:", len(files))
    return 0 if counts.get("OK", 0) == len(files) else 1


def print_trees(args, enable):
    g = Grammar(extract.extract(args.grammar), enable)
    jobs = [("<text>", args.text)] if args.text is not None else []
    for path in args.files:
        with open(path, encoding="utf-8") as fh:
            jobs.append((path, fh.read()))
    status = 0
    for label, text in jobs:
        lines, unique = tree_report(g, label, text, args.start, args.record)
        print("\n".join(lines))
        status = status or (0 if unique else 1)
    return status


def tree_report(g, label, text, start="source-file", record=False):
    """(lines, whether every parse has exactly one tree): each parse's tree
    count and the canonical dump of its trees, a source file's interpolation
    segments included (dump.report)."""
    import dump
    return dump.report(g, label, text, start, record)


if __name__ == "__main__":
    sys.exit(main())
