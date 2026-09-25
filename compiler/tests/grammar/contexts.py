"""The section-12 context of each construct occurrence in one derivation.

`cells` is the one entry point: it walks a derivation and returns one
(construct, context, parenthesized, "line:col") per occurrence of a context-matrix
row. A child's context comes from its parent's slot (`SLOTS` and the tables after
it); a production that is no occurrence passes its own context through.
`problems` checks the tables against the grammar, so a renamed production fails
loudly instead of silently leaving a cell unrecorded.

ENTRY POINTS
    cells
"""
import extract

INHERIT = "<inherit>"
PAREN = "<inherit, parenthesized>"
# The context a block gives its statements, by what owns the block; its last
# expression statement is `tail` whatever the owner.
BLOCK_KINDS = ("stmt", "clos", "catch")

# Occurrences written through a production or alternative that is not itself a
# matrix row: the constant grammar, the assignment target's bare name, and the
# optional assignment tested as a binding subject.
PRODUCTION_CONSTRUCTS = {
    "syntax.expr.name-ref": "syntax.expr.name",
    "syntax.const.expr": "syntax.expr.additive",
    "syntax.const.term": "syntax.expr.multiplicative",
    "syntax.const.layout-query": "syntax.expr.call",
}
ALTERNATIVE_CONSTRUCTS = {
    "syntax.const.atom.int": "syntax.expr.literal",
    "syntax.const.atom.name": "syntax.expr.name",
    "syntax.const.atom.group": "syntax.expr.paren",
    "syntax.const.unary.negate": "syntax.expr.unary",
    "syntax.stmt.binding-subject.chain-assign": "syntax.stmt.optional-assign",
    "syntax.stmt.binding-subject.borrow-chain-assign": "syntax.stmt.optional-assign",
}
# Productions that are a node only with an operator: one operand passes through.
CHAIN_NODES = {"Binary", "Coalesce", "Cast", "Range"}

# parent nonterminal -> {child nonterminal: context}. A child the map does not
# name gets its parent's context when the parent is no occurrence, else none.
SLOTS = {
    "closure-literal": {"block-body": "clos"},
    "catch-clause": {"block": "catch"},
    "arm-body": {"block": "stmt", "expr": "arm", "non-expr-statement": "arm"},
    "refusal-unit-item": {"statement": "stmt"},
    "attributed-local": {"let-stmt": INHERIT},
    "let-stmt": {"expr": "init"},
    "destructure-stmt": {"expr": "init"},
    "assign-stmt": {"assign-target": "atgt", "expr": "asgn"},
    "compound-assign-stmt": {"compound-target": "atgt", "expr": "crhs"},
    "binding-subject": {"head-expr": INHERIT, "optional-chain-target": "atgt",
                        "borrow-optional-target": "atgt", "expr": "asgn"},
    "return-stmt": {"expr": "ret"},
    "break-stmt": {"expr": "brk"},
    "lend-stmt": {"expr": "lend"},
    "guard-stmt": {"binding-subject": "subj"},
    "guard-condition": {"head-expr": "cond"},
    "static-assert": {"expr": "sassert"},
    "param": {"expr": "dflt"},
    "static-init": {"expr": "sinit"},
    "raw-value": {"expr": "raw"},
    "attribute": {"expr": "aarg"},
    "array-type": {"expr": "alen"},
    "array-literal": {"expr": "elem"},
    "tuple-expr": {"expr": "elem"},
    "tuple-field": {"expr": "elem"},
    "set-literal": {"expr": "elem"},
    "map-entry": {"expr": "elem"},
    "call-hop": {"arg-list": "arg", "closure-literal": "arg"},
    "trailing-hop": {"closure-literal": "arg"},
    "subscript-hop": {"expr": "idx"},
    "multi-subscript": {"expr": "idx", "arg-list": "idx"},
    "interp-segment": {"expr": "interp"},
    "generic-arg": {"const-expr": "cgen"},
    "generic-param": {"const-expr": "cgen"},
    "if-expr": {"if-head": "cond"},
    "else-if-arm": {"if-head": "cond"},
    "optional-binding": {"binding-subject": "subj"},
    "borrow-unwrap": {"head-expr": "subj"},
    "while-expr": {"head-expr": "cond"},
    "while-let-expr": {"head-expr": "subj"},
    "for-expr": {"head-expr": "iter"},
    "for-borrow": {"head-expr": "iter"},
    "match-expr": {"head-expr": "scrut"},
    "arm-guard": {"head-expr": "aguard"},
    "borrow-binding": {"head-expr": "bhead"},
    "try-expr": {"prefix-expr": "try"},
    "capture-list": {"capture": "cap"},
    "unary-expr": {"prefix-expr": "opnd"},
    "deref-expr": {"prefix-expr": "opnd"},
    "ref-expr": {"prefix-expr": "opnd"},
    "lends-expr": {"prefix-expr": "opnd"},
    "borrow-place": {"postfix-expr": "opnd"},
    "const-unary": {"const-unary": "opnd"},
    "const-atom": {"const-expr": PAREN},
    "paren-expr": {"expr": PAREN},
}
# A chain's operands, which are operands only when the chain has an operator;
# with one operand the chain passes its context through.
OPERANDS = {
    "compare-expr": "range-expr",
    "cast-expr": "prefix-expr",
    "bitor-expr": "bitxor-expr",
    "bitxor-expr": "bitand-expr",
    "bitand-expr": "compare-expr",
    "shift-expr": "additive-expr",
    "additive-expr": "multiplicative-expr",
    "multiplicative-expr": "cast-expr",
    "const-expr": "const-term",
    "const-term": "const-unary",
}
# `&&`, `||` and `??`: the first operand is an operand, every later one a right side.
SHORT_CIRCUIT = {"coalesce-expr": "or-expr", "or-expr": "and-expr", "and-expr": "bitor-expr"}
# A range's endpoints, which are `rend` when the range is a `for` iterable.
RANGES = ("range-expr", "range-from", "range-upto")
# Hop chains: the last hop stands in the chain's context, the rest are receivers.
CHAINS = ("postfix-expr", "projection-target", "call-target", "optional-chain-target")
# Slots that depend on a child's position or the parent's alternative (`_special`).
SPECIAL =("block-body", "try-block", "argument", "repeat-literal", "optional-assign-stmt")


class Walker:
    def __init__(self, parse):
        self.g = parse.g
        self.tokens = parse.tokens
        self.rows = {cells[0] for _, cells in self.g.model.rows_of(extract.MATRIX) if cells}
        self.out = []

    def flat(self, d):
        out = []
        for k in d.kids:
            if not isinstance(k, int) and k.nt.startswith("__"):
                out.extend(self.flat(k))
            else:
                out.append(k)
        return out

    def construct_of(self, d, kids):
        p = self.g.info[d.nt]
        alt = p.alternatives[d.ai]
        construct = (ALTERNATIVE_CONSTRUCTS.get(alt.effective_name)
                     or PRODUCTION_CONSTRUCTS.get(p.name)
                     or (p.name if p.name in self.rows else None))
        if construct is None:
            return None
        if (p.node in CHAIN_NODES and len(kids) == 1 and not isinstance(kids[0], int)):
            return None
        if len(alt.items) == 1 and extract.NONTERMINAL_RE.match(alt.items[0]):
            child = self.g.info.get(alt.items[0])
            if child is not None and (child.name in self.rows
                                      or child.name in PRODUCTION_CONSTRUCTS):
                return None
        return construct

    def walk(self, d, ctx, paren):
        kids = self.flat(d)
        construct = self.construct_of(d, kids)
        if construct is not None and ctx is not None:
            t = self.tokens[d.i]
            self.out.append((construct, ctx, paren, "%d:%d" % (t.line, t.column)))
        nts = [k for k in kids if not isinstance(k, int)]
        for kid, kctx, kparen in self.slots(d, nts, ctx, paren, construct is not None):
            self.walk(kid, kctx, kparen)

    def slots(self, d, nts, ctx, paren, occurs):
        nt = d.nt
        default = (None, False) if occurs else (ctx, paren)
        alt = self.g.info[nt].alternatives[d.ai].effective_name
        if nt in SPECIAL:
            return self._special(nt, alt, nts, ctx, default)
        if nt in CHAINS:
            if len(nts) == 1:
                return [(nts[0], ctx, paren)]
            return [(k, "recv", False) for k in nts[:-1]] + [(nts[-1], ctx, paren)]
        if nt in SHORT_CIRCUIT and occurs:
            operands = [k for k in nts if k.nt == SHORT_CIRCUIT[nt]]
            return [(k, "opnd" if n == 0 else "rhs", False) for n, k in enumerate(operands)]
        if nt in OPERANDS:
            if not occurs:
                return [(k, ctx, paren) for k in nts]
            return [(k, "opnd", False) if k.nt == OPERANDS[nt] else (k, None, False)
                    for k in nts]
        if nt in RANGES and occurs:
            role = "rend" if ctx == "iter" else "opnd"
            return [(k, role, False) if k.nt == "shift-expr" else (k, None, False) for k in nts]
        rule = SLOTS.get(nt, {})
        out = []
        for k in nts:
            if k.nt not in rule:
                out.append((k,) + default)
            elif rule[k.nt] == INHERIT:
                out.append((k, ctx, paren))
            elif rule[k.nt] == PAREN:
                out.append((k, ctx, True))
            else:
                out.append((k, rule[k.nt], False))
        return out

    def _special(self, nt, alt, nts, ctx, default):
        if nt == "block-body":
            kind = ctx if ctx in BLOCK_KINDS else "stmt"
            stmts = [k for k in nts if k.nt == "statement"]
            out = [(k, None, False) for k in nts if k.nt != "statement"]
            for n, k in enumerate(stmts):
                last = n == len(stmts) - 1
                is_expr = self.g.info[k.nt].alternatives[k.ai].effective_name \
                    == "syntax.stmt.statement.expr"
                out.append((k, "tail" if last and is_expr else kind, False))
            return out
        if nt == "try-block":
            blocks = [k for k in nts if k.nt == "block"]
            return [(k, "stmt" if n == 0 else "catch", False) for n, k in enumerate(blocks)]
        if nt == "argument":
            role = "idx" if ctx == "idx" else (
                "larg" if alt == "syntax.expr.argument.labelled" else "arg")
            return [(k, role, False) for k in nts]
        if nt == "repeat-literal":
            return [(k, "elem" if n == 0 else "rcnt", False) for n, k in enumerate(nts)]
        if nt == "optional-assign-stmt":
            compound = alt in ("syntax.stmt.optional-assign.compound",
                               "syntax.stmt.optional-assign.borrow-compound")
            out = []
            for k in nts:
                if k.nt in ("optional-chain-target", "borrow-optional-target"):
                    out.append((k, "atgt", False))
                elif k.nt == "expr":
                    out.append((k, "crhs" if compound else "asgn", False))
                else:
                    out.append((k,) + default)
            return out
        raise AssertionError(nt)


def cells(parse, derivation, root=None):
    """(construct, context, parenthesized, "line:col") per construct occurrence."""
    w = Walker(parse)
    w.walk(derivation, root, False)
    return w.out


def problems(model):
    """Every name these tables use that the grammar does not define, and every
    section-12 context no rule can produce."""
    out = []
    nts = {p.nonterminal for p in model.productions if p.nonterminal}
    names = {p.name for p in model.productions}
    alts = {a.effective_name for a in model.alternatives()}
    rows = {cells[0] for _, cells in model.rows_of(extract.MATRIX) if cells}
    contexts = set(model.context_names())
    produced = set(BLOCK_KINDS) | {"tail", "recv", "rhs", "opnd", "rend", "idx", "larg", "arg",
                                   "elem", "rcnt", "atgt", "asgn", "crhs"}
    for parent, rule in SLOTS.items():
        for nt in [parent] + list(rule):
            if nt not in nts:
                out.append("contexts: SLOTS names %s, which the grammar does not define" % nt)
        for ctx in rule.values():
            if ctx not in (INHERIT, PAREN):
                produced.add(ctx)
    for nt in list(SHORT_CIRCUIT) + list(SHORT_CIRCUIT.values()) + list(OPERANDS) \
            + list(OPERANDS.values()) + list(RANGES) + list(CHAINS) + list(SPECIAL) \
            + ["statement", "block", "shift-expr", "expr", "head-expr"]:
        if nt not in nts:
            out.append("contexts: %s is not a nonterminal of the grammar" % nt)
    for name, construct in PRODUCTION_CONSTRUCTS.items():
        if name not in names:
            out.append("contexts: %s is not a production" % name)
        if construct not in rows:
            out.append("contexts: %s is not a context-matrix row" % construct)
    for name, construct in ALTERNATIVE_CONSTRUCTS.items():
        if name not in alts:
            out.append("contexts: %s is not an alternative" % name)
        if construct not in rows:
            out.append("contexts: %s is not a context-matrix row" % construct)
    for name in ("syntax.stmt.statement.expr", "syntax.expr.argument.labelled",
                 "syntax.stmt.optional-assign.compound",
                 "syntax.stmt.optional-assign.borrow-compound"):
        if name not in alts:
            out.append("contexts: %s is not an alternative" % name)
    for ctx in sorted(produced - contexts):
        out.append("contexts: %s is not a section-12 context" % ctx)
    for ctx in sorted(contexts - produced):
        out.append("contexts: no rule produces the section-12 context %s" % ctx)
    return out
