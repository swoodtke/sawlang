"""The rewrite rules: each observed site becomes edits, or a flag, never a guess.

A site is one postfix chain that reaches a place (its hops grouped by the
chain's first token), or one closure-borrow call. Every rule reads the
instrument's type evidence -- the accessor, the element type and its copy
tier, whether the window writes -- and places its edits by tokens found at
the AST's anchors. A shape no rule covers, or a rule whose preconditions fail,
is flagged with its reason; a flagged file is copied unchanged (SL-418).

ENTRY POINTS
    plan_file
"""
import os
import re

from edits import Edit, TokenType

COPY_POLICIES = ("trivial", "retain")
# The reason prefixes a person acts on differently from a rule that did not apply.
RETIRED = "pins a retired rule: "
RETIRED_API = "tests a retired closure API: "
PANIC_GUARD = ("a panic test, and the migrated spelling reaches a different accessor, "
               "which panics differently (K14)")
# Right sides whose evaluation nothing can observe, so moving it is safe.
SIMPLE_VALUES = ("IntLiteral", "StringLiteral", "BoolLiteral", "FloatLiteral", "Identifier",
                 "NoneLiteral")
STD_PREFIXES = ("sawc/std/", "sawc/builtin.saw")
# The closure-borrow APIs whose target accessor SL:borrowing settles, with the
# binding keyword and how the head is spelled.
SETTLED_E = {
    ("Vector", "with_ref"): ("let", "index"),
    ("Vector", "with_var_ref"): ("var", "index"),
    ("Mutex", "lock"): ("var", "call"),
    ("SpinLock", "lock"): ("var", "call"),
}
UNSETTLED_E = {
    ("Arc", "with_unique"): "E.with-unique: the borrows accessor that replaces Arc.with_unique is not named",
    ("SpinLock", "try_lock"): "E.try-lock: the conditional lock accessor that replaces SpinLock.try_lock is not spelled",
}
# Positions where a `borrow` block, a primary expression whose value is its
# tail (SL:borrowing §2.1), may stand in place of the call. A condition or
# subject head is not one: there a `borrow` binding is the head's own form.
BLOCK_POSITIONS = {("ExpressionStatement", "expression"), ("LetStatement", "value"),
                   ("ReturnStatement", "value"), ("AssignStatement", "value"),
                   ("Block", "final_expr"), ("FunctionCall", "arguments"),
                   ("MethodCall", "arguments"), ("StructInit", "arguments"),
                   ("StringInterpolation", "expressions")}


class Site:
    """One row of MIGRATION_SITES.tsv."""

    def __init__(self, line, col, rule, status, evidence, reason=""):
        self.line, self.col, self.rule, self.status = line, col, rule, status
        self.evidence, self.reason = evidence, reason
        self.before = self.after = ""
        self.edits = []


class Plan:
    def __init__(self):
        self.sites = []

    def add(self, site):
        self.sites.append(site)
        return site

    @property
    def edits(self):
        return [e for s in self.sites if s.status == "rewritten" for e in s.edits]

    @property
    def flags(self):
        return [s for s in self.sites if s.status == "flagged"]


# ------------------------------------------------------------------ evidence
def base(struct):
    return (struct or "").split("$")[0]


def is_std(record):
    f = record.get("accessor_file") or ""
    return f.startswith(STD_PREFIXES)


def accessor_class(r):
    """`map` (std Map.[]), `getter` (std Vector.get / Map.get, value functions
    in the new std), `subscript` (any other `[]`), or `named`."""
    s = base(r.get("struct"))
    if r.get("subscript"):
        return "map" if s == "Map" and is_std(r) else "subscript"
    if r.get("method") == "get" and s in ("Vector", "Map") and is_std(r):
        return "getter"
    return "named"


def copyable(r):
    """Whether a copy of the element runs no code: no declared `copy()` and no
    deinit anywhere in it, which is the free tier. Only then can a value read
    stand where the original read the place without copying (SL:borrowing
    §5.2): a hook that counts copies would see the difference."""
    return r.get("tier") == "free"


def value_copyable(r):
    """Whether a whole-element value read may stay a value read. The original
    copies the element there too, once, exactly as getitem and `get` do, so a
    copy hook runs the same number of times (map_subscript_retain_oracle)."""
    return r.get("policy") in COPY_POLICIES


def retired_mode(r):
    """Why a window relies on use-site mode inference, or None (SL:borrowing §3:
    the root charge follows the accessor's declaration). A std accessor is left
    out, since the new std declares both flavors. The other direction needs no
    check: sawc refuses a writable lend from a `&self` accessor outside a cell
    type, so an exclusive window there is a refusal in both languages."""
    if is_std(r) or r.get("synthesized"):
        return None
    if r.get("accessor_self") == "var" and not r.get("exclusive") and not r.get("exclusive_only"):
        return ("a shared window through `%s.%s`, which is declared `&var self` (use-site "
                "mode inference, SL:borrowing §3)" % (base(r.get("struct")), r.get("method")))
    return None


# A code mention of `get` (`.get(`, or a backticked name ending in `get`) and
# the words that describe a place.
GET_CODE = re.compile(r"\.get\(|`[\w.]*\bget\b[^`]*`")
PLACE_WORDS = re.compile(r"\b(place|places|lend|lends|window|windows)\b", re.I)


def describes_get_as_place(meta, get_lines):
    """Whether the file says a std `get` is a place (SL:borrowing §9.1 K14):
    its name pairs `get` with a place word, its header pairs a code mention of
    `get` with one, or the comment block right above a `get` site uses one."""
    tokens = os.path.basename(meta.get("path") or "").split(".")[0].split("_")
    if "get" in tokens and any(PLACE_WORDS.fullmatch(t) for t in tokens):
        return True
    head = "\n".join(meta.get("header") or [])
    if GET_CODE.search(head) and PLACE_WORDS.search(head):
        return True
    lines = meta.get("lines") or []
    for ln in get_lines:
        k, block = ln - 2, []
        while 0 <= k < len(lines) and lines[k].strip().startswith("//"):
            block.append(lines[k])
            k -= 1
        if PLACE_WORDS.search(" ".join(block)):
            return True
    return False


CLOSURE_API_NAMES = re.compile(r"\bwith_var_ref\b|\bwith_ref\b|\bwith_unique\b")
CLOSURE_WORDS = re.compile(r"\b(closure|closures|callback|callbacks)\b", re.I)
# The closure API's own typing: explicit type arguments on the call, or a
# callback slot such as `(&var T) sync -> R`.
CLOSURE_TYPING = re.compile(r"\b(lock|try_lock|with_ref|with_var_ref|with_unique)\s*<"
                            r"|\((&var|&)\s*\w+\)\s*(unsafe\s+)?(sync\s+)?->")


def closure_api_subject(meta, callee):
    """What makes the file a test of the retired closure API it calls, or None:
    its name or header names `with_ref`, `with_var_ref` or `with_unique`, talks
    about closures, or spells the API's closure typing (SL:borrowing §9)."""
    head = "\n".join(meta.get("header") or [])
    name = os.path.basename(meta.get("path") or "")
    found = CLOSURE_API_NAMES.search(name) or CLOSURE_API_NAMES.search(head)
    if found:
        return "the file's name or header names `%s`" % found.group(0)
    if CLOSURE_WORDS.search(head):
        return "the file's header is about the closure its `%s` call takes" % callee
    if CLOSURE_TYPING.search(head):
        return "the file's header spells the closure typing of `%s`" % callee
    return None


def panics_differently(rule):
    """Whether a rewrite under `rule` moves a panic into another accessor: an
    unwrap `!` folded into a place, `get` spelled as a place, or a closure-borrow
    call spelled as its accessor."""
    return (rule.startswith("E.") or "map-unwrap" in rule
            or rule in ("K14.get-to-place", "A4.map-forced-store", "A2.map-forced-compound",
                        "G1.map-get", "G2.map-get"))


def evidence(r):
    return "%s.%s elem=%s tier=%s policy=%s %s%s" % (
        base(r.get("struct")), r.get("method"), r.get("elem"), r.get("tier"), r.get("policy"),
        "exclusive" if r.get("exclusive") else "shared",
        " optional" if r.get("optional") else "")


# ------------------------------------------------------------------ token helpers
class Tokens:
    def __init__(self, src):
        self.src = src

    def at(self, pos):
        return self.src.index_at(pos[0], pos[1])

    def tok(self, i):
        return self.src.tokens[i]

    def off(self, i):
        return self.src.tokens[i].off

    def next(self, i):
        return self.src.next(i)

    def prev(self, i):
        return self.src.prev(i)

    def kind(self, i):
        return None if i is None else self.src.tokens[i].kind

    def end(self, i):
        return self.src.end_of(i)

    def text(self, i, j):
        """Source text from token i through token j inclusive."""
        return self.src.text[self.off(i):self.end(j)]


def root_problem(tk, root_i):
    """Why a prefix at the chain's first token would not cover the chain, or
    None: a parenthesized root lets the prefix bind inside the parentheses."""
    if root_i is None:
        return "no token at the chain's first position"
    p = tk.prev(root_i)
    if p is not None and tk.kind(p) == TokenType.LPAREN:
        close = tk.src.match_close(p)
        after = tk.next(close) if close is not None else None
        if after is not None and tk.kind(after) in (TokenType.LBRACKET, TokenType.DOT,
                                                    TokenType.EXCLAIM, TokenType.QUESTION_DOT,
                                                    TokenType.QUESTION):
            return "the chain's root is parenthesized"
    if p is not None and tk.kind(p) in (TokenType.DOT, TokenType.QUESTION_DOT):
        return "the chain's first token follows a member dot"
    return None


def place_tokens(tk, r):
    """(open, close) token indices of the place's own brackets: the `[`/`]` of
    a subscript, or the `(`/`)` of an accessor call."""
    i = tk.at((r["line"], r["col"]))
    if i is None:
        return None
    if r.get("subscript"):
        if tk.kind(i) != TokenType.LBRACKET:
            return None
        return i, tk.src.match_close(i)
    # A method place is anchored at its `.`: DOT IDENT ( ... )
    if tk.kind(i) not in (TokenType.DOT, TokenType.QUESTION_DOT):
        return None
    name = tk.next(i)
    op = tk.next(name) if name is not None else None
    if op is None or tk.kind(op) != TokenType.LPAREN:
        return None
    return op, tk.src.match_close(op)


def simple_key(tk, open_i, close_i, key_type):
    """Whether the tokens between a place's brackets name a key that `&k` can
    borrow: a binding or a field path, of a non-reference type."""
    if key_type is None or key_type.startswith("&"):
        return False
    toks = []
    j = tk.next(open_i)
    while j is not None and j != close_i:
        toks.append(tk.kind(j))
        j = tk.next(j)
    if not toks or toks[0] not in (TokenType.IDENT, TokenType.SELF):
        return False
    for k, kind in enumerate(toks[1:], 1):
        want = TokenType.DOT if k % 2 else TokenType.IDENT
        if kind != want:
            return False
    return len(toks) % 2 == 1


# ------------------------------------------------------------------ chains
def group_chains(windows):
    """[(top, [nested...])] per chain, keyed by the chain's first token."""
    groups, seen = {}, set()
    for r in windows:
        # One source site is lowered once per specialization of its body.
        ident = (r["line"], r["col"], r["caller"], bool(r.get("nested_outer")))
        if ident in seen:
            continue
        seen.add(ident)
        key = tuple(r["recv_left"][:2])
        groups.setdefault(key, []).append(r)
    out = []
    for key in sorted(groups):
        recs = groups[key]
        tops = [r for r in recs if not r.get("nested_outer")]
        nested = sorted((r for r in recs if r.get("nested_outer")),
                        key=lambda r: (r["line"], r["col"]))
        out.append((key, tops, nested))
    return out


def category(r):
    """The survey's row letter for a top record (SL:borrow-survey)."""
    c = r["caller"]
    if c == "_assignment":
        if r.get("whole"):
            return "A2" if r.get("compound") else "A0"
        if r.get("force_whole"):
            return "A4"
        return "A1"
    if c == "_span_call":
        return "Fwd" if r.get("forwarded_lend") else "B"
    if c == "_chain_assign_window":
        return "C"
    if c == "_presence_condition":
        return "D3"
    if c == "_borrow_match":
        return "G4"
    if c == "_borrow_operand_window":
        return "G4-operand"
    if c == "_chain_window":
        if r.get("grand") == "_presence_desugar":
            return "G4-presence"
        if r.get("bare"):
            if r.get("optional") and not r.get("unwrap_read"):
                cls = accessor_class(r)
                return {"map": "D1", "getter": "D2"}.get(cls, "D5")
            return "G1" if value_copyable(r) else "G3"
        if r.get("exclusive"):
            return "A3"
        return "G2" if copyable(r) else "G3"
    return "?"


class Planner:
    """Plans one file."""

    def __init__(self, path, src, meta):
        self.path, self.src, self.meta = path, src, meta
        self.tk = Tokens(src)
        self.plan = Plan()
        self.used_names = {t.value for t in src.tokens if t.kind == TokenType.IDENT}
        self.nested = []
        self.get_is_place = False

    def survey(self, windows):
        """File-level evidence read before any site is planned."""
        get_lines = sorted({w["line"] for w in windows if accessor_class(w) == "getter"})
        self.get_is_place = bool(get_lines) and describes_get_as_place(self.meta, get_lines)

    # -- sites
    def site(self, r, rule, status, reason="", edits=(), line=None, col=None):
        if status == "rewritten" and self.meta.get("panic") and panics_differently(rule):
            status, reason, edits = "flagged", PANIC_GUARD, ()
            rule = rule.split(".")[0]
        s = Site(line or r["line"], col or r["col"], rule, status, evidence(r) if r else "", reason)
        s.edits = list(edits)
        return self.plan.add(s)

    def flag(self, r, rule, reason, line=None, col=None):
        return self.site(r, rule, "flagged", reason, line=line, col=col)

    def fresh(self, stem):
        name, n = stem, 1
        while name in self.used_names:
            name = "%s%d" % (stem, n)
            n += 1
        self.used_names.add(name)
        return name

    # -- chain rules
    def chain(self, tops, nested):
        if len(tops) != 1:
            for r in tops or nested[:1]:
                self.flag(r, "chain", "several windows share one chain head")
            return
        top = tops[0]
        cat = category(top)
        cls = accessor_class(top)
        if (top.get("exclusive") and top.get("shared_self_body") and top.get("root") == "self"
                and not top.get("self_cell")):
            return self.flag(top, "design-200", RETIRED + "a write through `self` inside a `&self` "
                                                "method (design 200's carve-out, SL:borrowing §9)")
        for r in [top] + list(nested):
            why = retired_mode(r)
            if why:
                return self.flag(top, "use-site-mode", RETIRED + why)
        if self.get_is_place and any(accessor_class(r) == "getter" for r in [top] + list(nested)):
            return self.flag(top, "get-place", RETIRED + "the file describes a std `get` as a "
                                               "place (SL:borrowing §9.1, K14)")
        if cat == "Fwd" or any(n.get("forwarded_lend") for n in nested):
            return self.flag(top, "Fwd", "lend forwarding through another accessor (K2)")
        # A Map or `get` hop inside the chain reads a container, so the chain
        # is a borrow; one whose element copies with no code would be a value
        # read that nothing here spells.
        for n in nested:
            if accessor_class(n) in ("map", "getter") and copyable(n):
                return self.flag(top, "nested", "a Map subscript or `get` hop of a Copy element "
                                                "inside a longer chain")
        nested_forces = any(accessor_class(n) != "subscript" or not copyable(n) for n in nested)
        handler = getattr(self, "cat_" + cat.replace("-", "_"), None)
        if handler is None:
            return self.flag(top, cat, "no rule covers this shape")
        self.nested = nested
        return handler(top, cls, nested, nested_forces)

    def prefix_edit(self, r, mode):
        """The `borrow let|var ` insertion at the chain's first token."""
        i = self.tk.at(r["recv_left"][:2])
        problem = root_problem(self.tk, i)
        if problem:
            return None, problem
        return Edit(self.tk.off(i), self.tk.off(i), "borrow %s " % mode), None

    def after_place(self, r):
        """The index of the token right after the place's closing bracket."""
        pt = place_tokens(self.tk, r)
        if pt is None or pt[1] is None:
            return None, None
        return pt, self.tk.next(pt[1])

    def borrow_chain(self, r, cls, mode, rule, nested=None):
        """Prefix the chain with `borrow let|var`, and give each Map subscript
        or std `get` hop in it the place spelling the new std lends through."""
        nested = self.nested if nested is None else nested
        edits = []
        if place_tokens(self.tk, r) is None:
            return self.flag(r, rule, "the place's own token is not at its anchor")
        pre, problem = self.prefix_edit(r, mode)
        if problem:
            return self.flag(r, rule, problem)
        edits.append(pre)
        suffixes = []
        for hop in [r] + list(nested):
            hop_cls = accessor_class(hop)
            if hop_cls not in ("map", "getter"):
                continue
            found = self.hop_edits(hop, hop_cls)
            if isinstance(found, tuple) and isinstance(found[0], str) and found[1] is None:
                return self.flag(r, found[2], found[0])
            hop_edits, suffix = found
            edits.extend(hop_edits)
            if suffix not in suffixes:
                suffixes.append(suffix)
        rule_used = rule
        if "K14.get-to-place" in suffixes:
            rule_used = "K14.get-to-place"
        elif suffixes:
            rule_used = rule + "".join(suffixes)
        return self.site(r, rule_used, "rewritten", edits=edits)

    def hop_edits(self, r, cls):
        """(edits, rule suffix) that spell one Map subscript or `get` hop as a
        place inside a borrow, or (why, None, rule) when none is settled."""
        pt, nxt = self.after_place(r)
        if pt is None:
            return ("the place's brackets were not found", None, "chain")
        kind = self.tk.kind(nxt)
        if kind == TokenType.EXCLAIM:
            if cls == "map":
                # `m[k]!` under a borrow: `[]` in a borrow panics on absence.
                return [Edit(self.tk.off(nxt), self.tk.end(nxt), "")], "+map-unwrap"
            if not self.single_argument(r):
                return ("`get` with other than one argument", None, "K14")
            dot = self.tk.at((r["line"], r["col"]))
            open_i, close_i = pt
            inner = self.src.text[self.tk.end(open_i):self.tk.off(close_i)]
            return [Edit(self.tk.off(dot), self.tk.end(nxt), "[%s]" % inner)], "K14.get-to-place"
        if kind == TokenType.QUESTION_DOT:
            if base(r.get("struct")) != "Map":
                return ("an optional chain through Vector.get: no conditional Vector accessor "
                        "is settled", None, "K14")
            found = self.find_edits(r, cls, pt)
            if isinstance(found, str):
                return (found, None, "C")
            return found, "+map-find"
        return ("a Map or `get` place used without `!` or `?`", None, "chain")

    def single_argument(self, r):
        args = r.get("args")
        return args is not None and len(args) == 1

    def find_edits(self, r, cls, pt):
        """`m[k]` / `m.get(k)` to `m.find(&k)`, or the reason it cannot be."""
        open_i, close_i = pt
        key_type = ((r.get("key") or {}).get("resolved") if cls == "map"
                    else ((r.get("args") or [{}])[0] or {}).get("resolved"))
        if cls == "getter" and not self.single_argument(r):
            return "`get` with other than one argument"
        if not simple_key(self.tk, open_i, close_i, key_type):
            return ("the key is not a binding or field path, so `find(&k)` would borrow a "
                    "temporary, which SL:borrowing does not settle")
        if cls == "map":
            return [Edit(self.tk.off(open_i), self.tk.end(open_i), ".find(&"),
                    Edit(self.tk.off(close_i), self.tk.end(close_i), ")")]
        name = self.tk.next(self.tk.at((r["line"], r["col"])))
        return [Edit(self.tk.off(name), self.tk.end(name), "find"),
                Edit(self.tk.end(open_i), self.tk.end(open_i), "&")]

    def map_value_read(self, r, rule, unwrap):
        """A value read of a Map subscript: `m[k]` becomes `m.get(k)`."""
        pt = place_tokens(self.tk, r)
        if pt is None or pt[1] is None:
            return self.flag(r, rule, "the place's brackets were not found")
        open_i, close_i = pt
        return self.site(r, rule, "rewritten", edits=[
            Edit(self.tk.off(open_i), self.tk.end(open_i), ".get("),
            Edit(self.tk.off(close_i), self.tk.end(close_i), ")")])

    # -- categories: writes
    def cat_A0(self, r, cls, nested, forces):
        if cls == "named":
            return self.borrow_chain(r, cls, "var", "A0.accessor-store")
        if cls == "subscript":
            if nested:
                return self.borrow_chain(r, cls, "var", "A0.nested-store")
            return None
        return self.flag(r, "A0", "a whole store through a Map subscript or `get`")

    def cat_A2(self, r, cls, nested, forces):
        if cls == "named":
            return self.borrow_chain(r, cls, "var", "A2.accessor-compound")
        if cls == "subscript" and copyable(r):
            if nested:
                return self.borrow_chain(r, cls, "var", "A2.nested-compound")
            return None
        return self.flag(r, "A2", "a whole-element compound assignment of an element whose "
                                  "copy is not free (not Copy, or its copy runs code)")

    def cat_A4(self, r, cls, nested, forces):
        if nested:
            return self.flag(r, "A4", "a forced store inside a longer chain")
        if cls == "named":
            return self.borrow_chain(r, cls, "var", "A4.accessor-forced-store")
        if cls == "map":
            if r.get("compound"):
                if not copyable(r):
                    return self.flag(r, "A2", "a forced compound store of an element whose "
                                              "copy is not free (not Copy, or its copy runs code)")
                pt, nxt = self.after_place(r)
                if pt is None or self.tk.kind(nxt) != TokenType.EXCLAIM:
                    return self.flag(r, "A2", "the forced unwrap was not found")
                return self.site(r, "A2.map-forced-compound", "rewritten",
                                 edits=[Edit(self.tk.off(nxt), self.tk.end(nxt), "")])
            return self.forced_store_block(r)
        return self.flag(r, "K14", "a store through `get`")

    def forced_store_block(self, r):
        """`m[k]! = v` to `borrow var e = m[k] { e = v }` (K7)."""
        value = r.get("value") or {}
        if value.get("type") not in SIMPLE_VALUES:
            return self.flag(r, "A4", "`m[k]! = v` whose right side is evaluated after the borrow "
                                      "opens in the block form: order would change")
        if r.get("root") in value.get("names", []):
            return self.flag(r, "A4", "the right side names the map")
        root_i = self.tk.at(r["recv_left"][:2])
        problem = root_problem(self.tk, root_i)
        if problem:
            return self.flag(r, "A4", problem)
        pt, bang = self.after_place(r)
        if pt is None or self.tk.kind(bang) != TokenType.EXCLAIM:
            return self.flag(r, "A4", "the forced unwrap was not found")
        eq = self.tk.next(bang)
        if self.tk.kind(eq) != TokenType.ASSIGN:
            return self.flag(r, "A4", "the assignment was not found")
        v_i = self.tk.at(value["pos"])
        v_end = self.tk.next(v_i) if v_i is not None else None
        if v_i is None or self.tk.kind(v_end) not in (TokenType.NEWLINE, TokenType.SEMICOLON,
                                                      TokenType.RBRACE, None):
            return self.flag(r, "A4", "the right side is not a single token")
        name = self.fresh("e")
        head = self.src.text[self.tk.off(root_i):self.tk.end(pt[1])]
        vtext = self.tk.text(v_i, v_i)
        edit = Edit(self.tk.off(root_i), self.tk.end(v_i),
                    "borrow var %s = %s { %s = %s }" % (name, head, name, vtext))
        return self.site(r, "A4.map-forced-store", "rewritten", edits=[edit])

    def cat_A1(self, r, cls, nested, forces):
        return self.borrow_chain(r, cls, "var", "A1.field-write")

    def cat_A3(self, r, cls, nested, forces):
        return self.borrow_chain(r, cls, "var", "A3.mutating-call")

    def cat_B(self, r, cls, nested, forces):
        """`&var x[i]` / `&x[i]` to `borrow var x[i]` / `borrow let x[i]` (K6)."""
        amp = self.tk.at(r["ref_pos"])
        if amp is None or self.tk.kind(amp) != TokenType.AMPERSAND:
            return self.flag(r, "B", "the reference sigil was not found")
        end = amp
        if r.get("ref_mutable"):
            end = self.tk.next(amp)
            if self.tk.kind(end) != TokenType.VAR:
                return self.flag(r, "B", "`&var` was not found")
        root_i = self.tk.at(r["recv_left"][:2])
        if root_i != self.tk.next(end):
            return self.flag(r, "B", "the reference does not start the chain")
        mode = "var" if r.get("ref_mutable") else "let"
        sigil = Edit(self.tk.off(amp), self.tk.off(root_i), "borrow %s " % mode)
        s = self.borrow_chain(r, cls, mode, "B.place-argument")
        if s.status == "rewritten":
            s.edits[0] = sigil
        return s

    def cat_C(self, r, cls, nested, forces):
        """`m[k]?.f = v` to `borrow var m.find(&k)?.f = v`."""
        if nested:
            return self.flag(r, "C", "a chain assignment inside a longer chain")
        value = r.get("value") or {}
        # An absent head skips a right side today unless the side names the
        # root, which sawc evaluates first (DF-218j); the borrow form's order
        # for a skipped side is not settled, so only an inert side moves.
        if (value.get("type") not in SIMPLE_VALUES
                and r.get("root") not in value.get("names", [])):
            return self.flag(r, "C", "a right side a conditional chain may skip, whose "
                                     "evaluation under the borrow form is not settled")
        pre, problem = self.prefix_edit(r, "var")
        if problem:
            return self.flag(r, "C", problem)
        if cls == "named":
            return self.site(r, "C.accessor-chain-assign", "rewritten", edits=[pre])
        if cls == "getter" and base(r.get("struct")) != "Map":
            return self.flag(r, "K14", "a chain write through Vector.get: no conditional Vector "
                                       "accessor is settled")
        if cls not in ("map", "getter"):
            return self.flag(r, "C", "a chain assignment through a conditional subscript: an "
                                     "optional place is a named accessor (SL:borrowing §5.1)")
        pt = place_tokens(self.tk, r)
        if pt is None or pt[1] is None:
            return self.flag(r, "C", "the place's brackets were not found")
        edits = self.find_edits(r, cls, pt)
        if isinstance(edits, str):
            return self.flag(r, "C", edits)
        return self.site(r, "C.find-chain-assign", "rewritten", edits=[pre] + edits)

    # -- categories: reads
    def cat_D1(self, r, cls, nested, forces):
        if nested or not value_copyable(r):
            return self.flag(r, "D1", "an optional read of a non-Copy Map value")
        return self.map_value_read(r, "D1.map-get", unwrap=False)

    def cat_D2(self, r, cls, nested, forces):
        if nested or not value_copyable(r):
            return self.flag(r, "D2", "an optional read through `get` of a non-Copy element")
        return None

    def cat_D5(self, r, cls, nested, forces):
        return self.flag(r, "D5", "an optional read of a conditional accessor: an inline "
                                  "conditional lend needs `!` or `?`")

    def cat_G1(self, r, cls, nested, forces):
        if cls == "map":
            if nested or not value_copyable(r):
                return self.flag(r, "G1", "a forced read of a non-Copy Map value")
            return self.map_value_read(r, "G1.map-get", unwrap=True)
        if cls == "getter":
            return None if value_copyable(r) and not nested else self.flag(r, "G1", "a non-Copy read through `get`")
        if cls == "named":
            return self.borrow_chain(r, cls, "let", "G1.accessor-read")
        if forces:
            return self.borrow_chain(r, cls, "let", "G1.nested-read")
        return None

    def cat_G2(self, r, cls, nested, forces):
        if cls == "named" or forces:
            return self.borrow_chain(r, cls, "let",
                                     "G2.accessor-read" if cls == "named" else "G2.nested-read")
        if cls == "map":
            pt, nxt = self.after_place(r)
            if pt is None or self.tk.kind(nxt) not in (TokenType.EXCLAIM, TokenType.QUESTION_DOT):
                return self.flag(r, "G2", "a Map read without `!` or `?`")
            return self.map_value_read(r, "G2.map-get", unwrap=True)
        return None

    def cat_G3(self, r, cls, nested, forces):
        if r.get("bare"):
            return self.flag(r, "G3", "a bare value read of a non-Copy element")
        return self.borrow_chain(r, cls, "let", "G3.borrow-let")

    def cat_G4(self, r, cls, nested, forces):
        if cls == "subscript" and copyable(r) and not nested:
            return None
        if cls == "map" and copyable(r) and not nested:
            return self.map_value_read(r, "G4.map-get", unwrap=False)
        return self.flag(r, "G4", "a `match` on a place that a copy cannot serve: the `borrow let` "
                                  "block needs each arm's payload bindings decided")

    def cat_G4_operand(self, r, cls, nested, forces):
        return self.borrow_chain(r, cls, "let", "G4.borrow-operand")

    def cat_G4_presence(self, r, cls, nested, forces):
        if cls == "subscript" and copyable(r) and not nested:
            return None
        if cls == "named" and not nested:
            return self.presence(r, cls, holder=self.presence_holder(r, desugared=True))
        return self.flag(r, "D3", "a presence test of a subscript's optional element whose "
                                  "copy is not free")

    def cat_D3(self, r, cls, nested, forces):
        if nested:
            return self.flag(r, "D3", "a presence test inside a longer chain")
        struct = base(r.get("struct"))
        if cls == "getter" and copyable(r):
            return None
        if not (cls in ("map", "named") or (cls == "getter" and struct == "Map")):
            return self.flag(r, "D3", "a presence test through Vector.get of an element whose "
                                      "copy is not free: no conditional Vector accessor is "
                                      "settled (K8)")
        return self.presence(r, cls, holder=self.presence_holder(r, desugared=False))

    def presence_holder(self, r, desugared):
        """The `if let _ =` / `guard let _ =` that tests the place, or None. A
        desugared test (an unconditional lend of an optional element) reaches
        the place pass without its holder, so the holder is found by tokens."""
        if not desugared:
            ctx = (r.get("ctx") or [{}])[0]
            if ctx.get("type") in ("IfLetExpr", "GuardLetStatement") and ctx.get("field") == "optional_expr":
                return self.tk.at(ctx["pos"])
            return None
        root_i = self.tk.at(r["recv_left"][:2])
        eq = self.tk.prev(root_i) if root_i is not None else None
        us = self.tk.prev(eq) if eq is not None else None
        let_i = self.tk.prev(us) if us is not None else None
        head = self.tk.prev(let_i) if let_i is not None else None
        if (self.tk.kind(eq) == TokenType.ASSIGN and self.tk.kind(let_i) == TokenType.LET
                and self.tk.tok(us).value == "_"
                and self.tk.kind(head) in (TokenType.IF, TokenType.GUARD)):
            return head
        return None

    def presence(self, r, cls, holder):
        """`if let _ = m[k]` to `if m.contains_key(k)`; through a conditional
        accessor, to the `borrow let` block that yields the answer (K8)."""
        if holder is None:
            return self.flag(r, "D3", "a presence test outside `if let _` / `guard let _`")
        let_i = self.tk.next(holder)
        if self.tk.kind(let_i) != TokenType.LET:
            return self.flag(r, "D3", "`while let` or an unexpected head")
        us = self.tk.next(let_i)
        eq = self.tk.next(us)
        root_i = self.tk.at(r["recv_left"][:2])
        if self.tk.kind(eq) != TokenType.ASSIGN or self.tk.next(eq) != root_i or self.tk.tok(us).value != "_":
            return self.flag(r, "D3", "the presence test's `_ =` was not found")
        pt = place_tokens(self.tk, r)
        if pt is None or pt[1] is None:
            return self.flag(r, "D3", "the place's brackets were not found")
        open_i, close_i = pt
        if cls == "named":
            problem = root_problem(self.tk, root_i)
            if problem:
                return self.flag(r, "D3", problem)
            name = self.fresh("e")
            head_text = self.src.text[self.tk.off(root_i):self.tk.end(close_i)]
            after = self.tk.next(close_i)
            if self.tk.kind(after) not in (TokenType.LBRACE, TokenType.ELSE):
                return self.flag(r, "D3", "the presence test's subject continues past the accessor")
            block = "(borrow let %s = %s { if let _ = %s { true } else { false } })" % (
                name, head_text, name)
            return self.site(r, "D3.borrow-block", "rewritten", edits=[
                Edit(self.tk.off(let_i), self.tk.end(close_i), block)])
        edits = [Edit(self.tk.off(let_i), self.tk.off(root_i), "")]
        if cls == "map":
            edits += [Edit(self.tk.off(open_i), self.tk.end(open_i), ".contains_key("),
                      Edit(self.tk.off(close_i), self.tk.end(close_i), ")")]
        else:
            name = self.tk.next(self.tk.at((r["line"], r["col"])))
            edits.append(Edit(self.tk.off(name), self.tk.end(name), "contains_key"))
        return self.site(r, "D3.contains-key", "rewritten", edits=edits)

    # -- closure-borrow calls
    def closure(self, c):
        owner = base(c.get("owner"))
        key = (owner, c.get("callee"))
        if owner == "Arc" and c.get("callee") == "lock":
            key = ("Mutex", "lock")
        from_std = (c.get("callee_file") or "").startswith(STD_PREFIXES) or owner == "Arc"
        if (key in UNSETTLED_E or key in SETTLED_E) and from_std:
            subject = closure_api_subject(self.meta, c.get("callee"))
            if subject:
                return self.flag(c, "E", RETIRED_API + subject, line=c["line"], col=c["col"])
        if key in UNSETTLED_E:
            return self.flag(c, "E", UNSETTLED_E[key], line=c["line"], col=c["col"])
        if key not in SETTLED_E or not from_std:
            return None
        rule = "E.%s" % c["callee"].replace("_", "-")
        if c.get("captures_root"):
            return self.flag(c, "K10", "the closure names its call's own root", c["line"], c["col"])
        exits = [x for x in c.get("exits") or [] if x in ("return", "try")]
        if exits:
            return self.flag(c, rule, "the closure body has %s, which a block would retarget"
                             % "/".join(exits), c["line"], c["col"])
        if c.get("shorthand") or len(c.get("params") or []) != 1:
            return self.flag(c, rule, "the closure has no single named parameter to bind",
                             c["line"], c["col"])
        caps = [x for x in c.get("capture_specs") or [] if x["mode"] not in ("ref", "ref_var")]
        if caps:
            return self.flag(c, rule, "the closure captures by value", c["line"], c["col"])
        if c.get("shadow_risk"):
            return self.flag(c, rule, "the closure's parameter name is bound elsewhere in the "
                                      "function, so the borrow binding could shadow it",
                             c["line"], c["col"])
        ctx = (c.get("ctx") or [{}])[0]
        where = (ctx.get("type"), (ctx.get("field") or "").split("[")[0])
        if where not in BLOCK_POSITIONS:
            return self.flag(c, rule, "the call stands where a `borrow` block would change the "
                                      "parse (%s.%s)" % where, c["line"], c["col"])
        mode, head_kind = SETTLED_E[key]
        return self.closure_block(c, rule, mode, head_kind)

    def closure_block(self, c, rule, mode, head_kind):
        tk = self.tk
        flag = lambda why: self.flag(c, rule, why, c["line"], c["col"])  # noqa: E731
        root_i = tk.at(c["recv_left"][:2])
        problem = root_problem(tk, root_i)
        if problem:
            return flag(problem)
        dot = tk.at((c["line"], c["col"]))
        if tk.kind(dot) != TokenType.DOT:
            return flag("the call's `.` was not found")
        name_i = tk.next(dot)
        after_name = tk.next(name_i)
        if tk.kind(after_name) == TokenType.LT:
            # Explicit type arguments name the closure's result type, which
            # the block's tail determines.
            k, depth = after_name, 0
            while k is not None:
                if tk.kind(k) == TokenType.LT:
                    depth += 1
                elif tk.kind(k) == TokenType.GT:
                    depth -= 1
                    if depth == 0:
                        break
                elif tk.kind(k) in (TokenType.LBRACE, TokenType.NEWLINE):
                    k = None
                    break
                k = tk.next(k)
            if k is None:
                return flag("the call's type arguments were not read")
            after_name = tk.next(k)
        brace = tk.at(c["closure_pos"])
        if brace is None or tk.kind(brace) != TokenType.LBRACE:
            return flag("the closure's brace was not found")
        close_brace = tk.src.match_close(brace)
        param = (c["params"] or [{}])[0]
        in_i = None
        j = tk.next(brace)
        while j is not None and j != close_brace:
            if tk.kind(j) == TokenType.IN:
                in_i = j
                break
            j = tk.next(j)
        if in_i is None:
            return flag("the closure's `in` was not found")
        # The call's own parentheses, if the closure is inside them.
        call_end = close_brace
        paren_close = None
        if tk.kind(after_name) == TokenType.LPAREN:
            paren_close = tk.src.match_close(after_name)
            if paren_close is not None and tk.off(paren_close) > tk.off(close_brace):
                call_end = paren_close
                if tk.prev(paren_close) != close_brace:
                    return flag("tokens follow the closure inside the call's parentheses")
        recv = self.src.text[tk.off(root_i):tk.off(dot)]
        if head_kind == "index":
            args = c.get("args") or []
            if len(args) != 2 or c.get("arg_index") != 1:
                return flag("with_ref/with_var_ref without exactly an index and a closure")
            idx_i = tk.at(args[0]["left"][:2])
            if idx_i is None:
                return flag("the index argument was not found")
            comma = idx_i
            depth_close = paren_close
            k = idx_i
            while k is not None and k != depth_close and tk.kind(k) != TokenType.COMMA and k != brace:
                if tk.kind(k) in (TokenType.LPAREN, TokenType.LBRACKET, TokenType.LBRACE):
                    k = tk.src.match_close(k)
                comma = k
                k = tk.next(k)
            index_text = self.src.text[tk.off(idx_i):tk.end(comma)]
            if c.get("arg_labels", [None])[0]:
                return flag("a labelled index argument")
            head = "%s[%s]" % (recv, index_text)
        else:
            if c.get("n_args") != 1:
                return flag("a lock call with more than the closure")
            head = "%s.%s()" % (recv, c["callee"])
        # The body keeps its own text and line breaks; only the head changes.
        opening = "borrow %s %s = %s {" % (mode, param["name"], head)
        edits = [Edit(tk.off(root_i), tk.end(in_i), opening)]
        if call_end != close_brace:
            edits.append(Edit(tk.end(close_brace), tk.end(call_end), ""))
        s = self.site(c, rule, "rewritten", edits=edits, line=c["line"], col=c["col"])
        s.evidence = "%s.%s closure=%s" % (base(c.get("owner")), c["callee"], c.get("closure_type"))
        return s


def plan_file(path, src, windows, closures, meta):
    """The Plan for one file: its sites, rewritten or flagged."""
    p = Planner(path, src, meta)
    # A synthesized declaration's windows have no source of their own.
    windows = [w for w in windows if not w.get("synthesized")]
    p.survey(windows)
    for _, tops, nested in group_chains(windows):
        p.chain(tops, nested)
    for c in sorted(closures, key=lambda c: (c["line"], c["col"], c["arg_index"])):
        p.closure(c)
    return p.plan
