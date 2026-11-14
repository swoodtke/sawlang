"""The one rule for the header lines of a fixture's leading comment.

A lane reads a fixture's first comment lines as headers (`// refuses: RULE at
L:C`, `// flags: FLAGS`, `// message: TEXT`, ...). A line that begins like a
header and does not parse is read as an ordinary comment, so the check it
asked for never runs. `problems` is the check every lane applies, with its
own `Rule`: a line that begins with one of the lane's header words must be a
header the lane reads, on the row the lane reads it from, stated once unless
the header repeats.

ENTRY POINTS
    Header          one header word: its pattern, its form, its row, its repeat
    Rule            a lane's header words, misspellings and ordering
    problems        [(row, line, sentence)] for a list of lines
    file_problems   the same for a file's leading comment
"""
import re

_ORDINAL = {1: "first", 2: "second", 3: "third", 4: "fourth"}


class Header:
    """One header word. `pattern` matches a well-formed line, `form` is how
    the failure sentence spells it, `rows` the rows (1-based) the lane reads
    it from, None for any, `repeat` whether it may be stated twice, and
    `detect` the regex text a line begins with when it is meant as this
    header (the word itself by default)."""

    def __init__(self, word, pattern, form, rows=None, repeat=False, detect=None):
        self.word = word
        self.pattern = re.compile(pattern)
        self.form = form
        self.rows = rows
        self.repeat = repeat
        self.detect = detect if detect is not None else re.escape(word)


class Rule:
    """A lane's header words. `misspelt` maps a spelling no pattern reads to
    the word it was meant for, and `before` lists (A, B) pairs: A goes before
    the first B."""

    def __init__(self, headers, misspelt=None, before=()):
        self.headers = list(headers)
        self.by_word = {h.word: h for h in self.headers}
        self.misspelt = dict(misspelt or {})
        self.before = tuple(before)
        # (matcher, header, misspelt) in the order tried.
        self.matchers = []
        for h in self.headers:
            self.matchers.append((self._matcher(h.detect), h, False))
        for spelling, word in self.misspelt.items():
            self.matchers.append((self._matcher(re.escape(spelling)), self.by_word[word], True))

    @staticmethod
    def _matcher(detect):
        return re.compile(r"^//\s*(?:%s)(?![A-Za-z0-9_])" % detect)

    def with_rows(self, rows):
        """A copy whose headers read from `rows` ({word: rows}) where it
        names them: the same word is on another row in another kind of
        fixture."""
        copy = Rule([Header(h.word, h.pattern.pattern, h.form, rows.get(h.word, h.rows), h.repeat, h.detect)
                     for h in self.headers], self.misspelt, self.before)
        return copy


def _rows_sentence(rows):
    return " or ".join(_ORDINAL.get(r, "row %d" % r) for r in rows)


def problems(lines, rule):
    """[(row, line, sentence)] for each leading comment line of `lines` that
    begins like a header of `rule` and is not one the lane reads: it does not
    parse, it is on the wrong row, it repeats a header that may not repeat,
    or it is out of order. The leading comment ends at the first line that
    does not start with `//`."""
    found = []
    seen = set()
    for row, line in enumerate(lines, 1):
        if not line.startswith("//"):
            break
        for matcher, header, spelt in rule.matchers:
            if matcher.match(line):
                break
        else:
            continue
        if spelt or not header.pattern.match(line):
            found.append((row, line, "a header line the lane cannot read: `%s` (a header is `%s`)"
                          % (line, header.form)))
            continue
        for first, second in rule.before:
            if header.word == first and second in seen:
                found.append((row, line, "`// %s:` goes before the first `// %s:`: `%s`" % (first, second, line)))
        if header.rows is not None and row not in header.rows:
            found.append((row, line, "`// %s:` goes on the %s row: `%s`"
                          % (header.word, _rows_sentence(header.rows), line)))
        if header.word in seen and not header.repeat:
            found.append((row, line, "`// %s:` is stated twice: `%s`" % (header.word, line)))
        seen.add(header.word)
    return found


def file_problems(path, rule):
    """`problems` over the file at `path`."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    return problems(lines, rule)
