"""One file through the passes: mechanical, grammar, manual; its statuses.

A file with an unresolved flag is copied unchanged, so a migrated file is
never half-migrated. Grammar edits come before mechanical ones in the edit
list, so a parenthesis and a `borrow` prefix at one offset nest the right way.
"""
import collections

import edits
import grammar_pass
import layout
import manifest
import mechanical
import scan
import verify

# The rule of a manual row that only accompanies the row before it.
COMPANION = "+"
# A companion that removes its whole line, newline included: an edit's `new`
# text cannot remove a line, and an emptied line is a stray blank.
DROP = "+drop"
COMPANIONS = (COMPANION, DROP)
# The rule of a manual row that resolves no flag: a person's hold on a whole
# file (a re-aim of an unflagged file), which its companions then edit.
ANCHOR = "reaim"


class Result:
    def __init__(self, path):
        self.path = path
        self.text = None
        self.statuses = []
        self.rules = collections.Counter()
        self.notes = []
        self.sites = []

    def row(self):
        return {"path": manifest.rel(self.path), "status": ",".join(self.statuses),
                "rules": ",".join("%s:%d" % kv for kv in sorted(self.rules.items())),
                "notes": "; ".join(self.notes)}


def site_row(path, line, col, rule, status, before="", after="", evidence="", reason=""):
    return {"path": manifest.rel(path), "line": line, "col": col, "rule": rule,
            "status": status, "before": before, "after": after, "evidence": evidence,
            "reason": reason}


def panic_test(text):
    """Whether the file expects a panic: `// EXPECT: panic` or any
    `// EXPECT-PANIC-*` directive."""
    return layout.directive(text) == "panic" or any(
        "// EXPECT-PANIC-" in line for line in layout.header(text))


def touched_lines(text, spans):
    """The lines of `text` that the (start, end) offset spans touch, each
    stripped, joined by a newline: a site's before or after cell."""
    idx = set()
    for start, end in spans:
        idx.update(range(text.count("\n", 0, start), text.count("\n", 0, end) + 1))
    lines = text.split("\n")
    return "\n".join(lines[i].strip() for i in sorted(idx))


def shifted(pos, later):
    """Where offset `pos` of a text lands once the `later` edits apply to it."""
    for e in sorted(later, key=lambda e: e.start):
        if e.end > pos:
            break
        pos += len(e.text) - (e.end - e.start)
    return pos


def changes(m):
    """Whether a manual row edits its line, rather than leaving it as it is."""
    return m["rule"] == DROP or m["old"] != m["new"]


def manual_edits(path, text, rows):
    """{(line, col): Edit} for each manual row that changes its line: its `old`
    text, which must occur exactly once on that line of the mechanically
    migrated text, becomes `new` (which may span lines); a drop row's `old` is
    its whole line, which goes. The mechanical edits keep every line where it
    was, so the rows' line numbers hold."""
    lines = text.split("\n")
    out, start = {}, [0]
    for line in lines:
        start.append(start[-1] + len(line) + 1)
    for m in rows:
        if not changes(m):
            continue
        line = lines[m["line"] - 1]
        if m["rule"] == DROP:
            if m["old"] != line or m["new"]:
                raise ValueError("%s:%d: a drop row's old text is its whole line, and its new "
                                 "text is empty" % (path, m["line"]))
            begin = start[m["line"] - 1]
            out[(m["line"], m["col"])] = edits.Edit(begin, min(start[m["line"]], len(text)), "")
            continue
        if line.count(m["old"]) != 1:
            raise ValueError("%s:%d: manual row's old text is not on its line exactly once: %r"
                             % (path, m["line"], m["old"]))
        off = start[m["line"] - 1] + line.index(m["old"])
        out[(m["line"], m["col"])] = edits.Edit(off, off + len(m["old"]), m["new"])
    return out


def process(job):
    """The Result for one `examples/` file. `job` is a plain dict so it can
    cross a process boundary."""
    path, text = job["path"], job["text"]
    res = Result(path)
    if not path.endswith(".saw"):
        return document(res, text, job.get("manual") or [])
    kind = layout.directive(text)
    error_test = kind == "error"
    panics = panic_test(text)
    passes = job["passes"]
    lines = text.split("\n")
    meta = {"expect": kind, "panic": panics, "path": path, "header": layout.header(text),
            "lines": lines}
    # (rule, line, col, reason) of every flag; applied sites as
    # (row, edits) so each row's after-text is its own edits' text.
    flags, file_edits, grammar_edits, grammar_rules = [], [], [], []
    applied = []

    def line_of(n):
        return lines[n - 1].strip() if n else ""

    # -- mechanical: the instrument's sites, then the blind spots
    plan = None
    if "mechanical" in passes:
        obs = _Obs(job)
        plan, problem = mechanical.run(path, text, obs, meta)
        if problem:
            # A text the lexer refuses holds no code to migrate.
            res.notes.append("the lexer refuses the text")
        if plan is not None:
            for s in plan.sites:
                if s.status == "flagged":
                    flags.append((s.rule, s.line, s.col, s.reason))
                else:
                    file_edits.extend(s.edits)
        for line, col, region, shape in _unseen(job, text):
            flags.append(("unseen", line, col, "no type evidence: %s in %s" % (shape, region)))

    # -- grammar: removed productions, then the meaning-preservation check
    expected = job.get("expected")
    if "grammar" in passes:
        if expected is not None and not error_test and expected[1].startswith("a-removed:"):
            found, why = grammar_pass.removed_form_edits(text, expected[1])
            if why:
                flags.append(("removed-form", 0, 0, why))
            else:
                for line, col, e in found:
                    grammar_edits.append(e)
                    grammar_rules.append("grammar.export-to-public-import")
                    applied.append((site_row(path, line, col, "grammar.export-to-public-import",
                                             "rewritten", line_of(line), "",
                                             "corpus_expected.tsv: %s" % expected[1]), [e]))
        sites, _ = grammar_pass.meaning_sites(text)
        for s in sites:
            if s.status == "flagged":
                flags.append((s.ruling, s.line, s.col, s.reason))
            else:
                grammar_edits.extend(s.edits)
                grammar_rules.append(s.ruling)
                applied.append((site_row(path, s.line, s.col, s.ruling, "rewritten",
                                         line_of(s.line), "",
                                         "sawc AST unchanged, recognizer tree changed"), s.edits))

    # -- manual: each row resolves one flag at its (line, col), by editing it
    # or by leaving it as it is; a row whose rule is `+` or `+drop` is a
    # companion edit of the row before it, and an anchor row lets companions
    # edit a file that has no flag of its own.
    manual = job.get("manual") or []
    for m in manual:
        if m["rule"] == ANCHOR and ((m["line"], m["col"]) != (0, 0) or m["old"] != m["new"]):
            raise ValueError("%s: an anchor row sits at line 0, column 0, and edits nothing" % path)
    resolving = {(m["line"], m["col"]): m for m in manual if m["rule"] not in COMPANIONS + (ANCHOR,)}
    flagged_at = {(f[1], f[2]): f for f in flags}
    for key, m in resolving.items():
        if key not in flagged_at or flagged_at[key][0] != m["rule"]:
            raise ValueError("%s:%d:%d: manual row for %s resolves no flag of that rule"
                             % (path, key[0], key[1], m["rule"]))
    unresolved = sorted((f for f in flags if (f[1], f[2]) not in resolving),
                        key=lambda f: (f[1], f[2], f[0]))

    def manual_status(m):
        return "reviewed" if m["old"] == m["new"] else "manual"

    def flag_row(rule, line, col, reason, before, evidence=""):
        m = resolving.get((line, col))
        if m is None:
            return site_row(path, line, col, rule, "flagged", before, "", evidence, reason)
        return site_row(path, line, col, rule, manual_status(m), before, "", evidence,
                        m["rationale"])

    if plan is not None:
        for s in plan.sites:
            if s.status == "flagged":
                res.sites.append(flag_row(s.rule, s.line, s.col, s.reason, s.before, s.evidence))
            else:
                applied.append((site_row(path, s.line, s.col, s.rule, "rewritten", s.before, "",
                                         s.evidence, s.reason), s.edits))
    for f in flags:
        if f[0] in ("unseen", "tool", "removed-form") or f[0].startswith("SL-"):
            res.sites.append(flag_row(f[0], f[1], f[2], f[3], line_of(f[1])))
    dropped = {(m["line"], m["col"]) for m in manual if m["rule"] == DROP}
    for m in manual:
        if m["rule"] in COMPANIONS:
            res.sites.append(site_row(path, m["line"], m["col"], m["parent"] + ".companion",
                                      "manual", line_of(m["line"]), "", "", m["rationale"]))
        elif m["rule"] == ANCHOR:
            res.sites.append(site_row(path, 0, 0, ANCHOR, "reviewed", reason=m["rationale"]))

    new = text
    if not unresolved:
        by_hand, landed = {}, {}
        machine = grammar_edits + file_edits
        try:
            mid, spans = edits.apply_mapped(text, machine)
            if manual and mid.count("\n") != text.count("\n"):
                raise ValueError("%s: the mechanical edits moved lines that manual rows name" % path)
            by_hand = manual_edits(path, mid, manual)
            hand = [by_hand[k] for k in sorted(by_hand)]
            new, hand_spans = edits.apply_mapped(mid, hand)
            # Each cell is read through where its own edits landed, so a
            # neighbour that adds or removes lines cannot shift it.
            landed = {id(e): (shifted(a, hand), shifted(b, hand)) for e, (a, b) in zip(machine, spans)}
            landed.update((id(e), s) for e, s in zip(hand, hand_spans))
            problem = check(text, new, file_edits) if new != text else None
        except edits.Overlap as e:
            problem = "overlapping edits: %s" % e
        if problem:
            unresolved.append(("tool", 0, 0, "verification: %s" % problem))
            res.sites.append(site_row(path, 0, 0, "tool", "flagged", reason=unresolved[-1][3]))
            new = text
        else:
            res.rules.update(grammar_rules)
            if plan is not None:
                res.rules.update(s.rule for s in plan.sites if s.status == "rewritten")
            for row in res.sites:
                if row["status"] in ("manual", "reviewed"):
                    res.rules[row["status"] + "." + row["rule"]] += 1
                if row["status"] == "manual" and (row["line"], row["col"]) not in dropped:
                    e = by_hand[(row["line"], row["col"])]
                    row["after"] = touched_lines(new, [landed[id(e)]])
            for row, site_edits in applied:
                row["before"] = touched_lines(text, [(e.start, e.end) for e in site_edits])
                row["after"] = touched_lines(new, [landed[id(e)] for e in site_edits])
    for row, _ in applied:
        res.sites.append(row)
    res.text = new

    # -- statuses
    if unresolved:
        first = unresolved[0]
        why = "withheld: the file keeps a flagged site, %s at %d:%d" % (first[0], first[1], first[2])
        for row in res.sites:
            if row["status"] in ("rewritten", "manual", "reviewed"):
                row["status"], row["after"], row["reason"] = "withheld", "", why
        res.statuses.append("flagged")
        reasons = collections.Counter(_reason_key(f) for f in unresolved)
        res.notes.extend("%s x%d" % kv if kv[1] > 1 else kv[0] for kv in sorted(reasons.items()))
    else:
        changed_by_hand = any(changes(m) for m in manual)
        rewritten = any(not k.startswith(("manual.", "reviewed.")) for k in res.rules)
        if changed_by_hand:
            res.statuses.append("manual")
        if rewritten:
            res.statuses.append("rewritten")
        if not changed_by_hand and not rewritten:
            res.statuses.append("reviewed" if manual else "copied")
    # A hand edit can turn a success test into a refusal or a panic test, and
    # the new expectation is as unconfirmed as a migrated one.
    if (error_test or layout.directive(new) == "error"
            or (new != text and (panics or panic_test(new)))):
        res.statuses.append("expectation-pending")
    if error_test:
        frozen_error, grammar_ok = grammar_pass.parse_outcomes(text, new, path)
        if (frozen_error is None) != grammar_ok:
            res.statuses.append("grammar-flip")
            res.notes.append("grammar-flip: %s" % (
                "GRAMMAR.md accepts what the frozen parser refuses (%s)" % frozen_error if grammar_ok
                else "GRAMMAR.md refuses what the frozen parser accepts (%s)"
                % (expected[1] if expected else verify.tree(new)[1])))
    if any("EXPECT-IR-" in line for line in layout.header(text)):
        res.statuses.append("ir-test")
    for x in manifest.xfail_lines(text):
        res.notes.append("xfail twin: %s" % x)
    return res


def document(res, text, manual):
    """A file that is not Saw source, such as an INDEX.md: copied, or edited by
    its manual rows, which have no flag to resolve since nothing is scanned."""
    res.text = text
    if not manual:
        res.statuses = ["copied"]
        return res
    by_hand = manual_edits(res.path, text, manual)
    hand = [by_hand[k] for k in sorted(by_hand)]
    new, spans = edits.apply_mapped(text, hand)
    landed = {id(e): s for e, s in zip(hand, spans)}
    lines = text.split("\n")
    for m in manual:
        status = "manual" if changes(m) else "reviewed"
        rule = m["parent"] + ".companion" if m["rule"] in COMPANIONS else m["rule"]
        row = site_row(res.path, m["line"], m["col"], rule, status, lines[m["line"] - 1].strip(),
                       "", "", m["rationale"])
        if status == "manual" and m["rule"] != DROP:
            row["after"] = touched_lines(new, [landed[id(by_hand[(m["line"], m["col"])])]])
        res.sites.append(row)
        res.rules[status + "." + rule] += 1
    res.text = new
    res.statuses = ["manual" if new != text else "reviewed"]
    return res


def check(text, new, file_edits):
    """None when the migrated text passes the grammar checks, else why not.
    A text the grammar refuses before migration (an error test, a removed
    form) owes only what the grammar pass fixed."""
    accepted = verify.verdict(text) == "OK"
    if accepted:
        problem = verify.check_prefixes(text, file_edits, edits.apply)
        if problem:
            return problem
    if (accepted or layout.directive(text) != "error") and verify.verdict(new) != "OK":
        return "the migrated text is refused by the grammar: %s" % verify.tree(new)[1]
    return None


def _reason_key(f):
    return "%s: %s" % (f[0], f[3])


class _Obs:
    """The slice of Observations one job carries."""

    def __init__(self, job):
        self.windows = {job["path"]: job.get("windows") or []}
        self.closures = {job["path"]: job.get("closures") or []}


def _unseen(job, text):
    try:
        program = scan.parse(text, job["path"])
    except Exception:  # noqa: BLE001 - a text sawc refuses has no regions to scan
        return []
    walked = set(tuple(w) for w in job.get("walked") or [])
    return scan.candidates(program, walked, job["accessors"])
