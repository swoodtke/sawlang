#!/usr/bin/env python3
"""The shared header rule (`compiler/tools/fixture_headers.py`) against each
lane's own header words.

    python compiler/tests/test_fixture_headers.py

`compiler/tests/run.py` runs `run()` in its `fixture_whitespace` step. For every
header word of every lane's rule it holds:

- the header with no space after its colon is a failure naming its form;
- prose that begins with the word is a failure, and a word that only starts the
  same (`refusesish`) is not;
- a header on a row its rule does not read it from is a failure;
- a header the rule does not let repeat is a failure when stated twice;
- no header after the leading comment is looked at.

Two more cases hold the ordering rule (a typecheck `// errors:` before the
first `// message:`) and the multi-word header spellings.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(COMPILER, "tools"))
for lane in ("typecheck", "resolve", "mir", "borrowck", "drops", "mono", "coro", "eval", "std"):
    sys.path.insert(0, os.path.join(HERE, lane))
sys.path.insert(0, HERE)

import fixture_headers  # noqa: E402

# A well-formed line of each header word any lane reads.
SAMPLES = {
    "refuses": "// refuses: rule.name at 3:4",
    "shadowed": "// shadowed: rule.name at 3:4",
    "due": "// due: rule.name when the slice reaches it",
    "flags": "// flags: --runtime",
    "errors": "// errors: 1",
    "message": "// message: some text",
    "warns": "// warns: 1",
    "stage 0": "// stage 0: cannot parse it",
    "stage0": "// stage0: name.saw",
}
LANES = ("typecheck_lane", "resolve_lane", "mir_lane", "borrowck_lane", "drops_lane", "mono_lane", "coro_lane",
         "eval_lane", "std_lane")


def lane_rules():
    """[(label, rule)] for each rule of each lane, a lane with a rule per
    kind of fixture giving each."""
    out = []
    for name in LANES:
        module = __import__(name)
        kinds = getattr(module, "HEADER_KINDS", None)
        if kinds is not None:
            out += [("%s %s" % (name, kind), rule) for kind, rule in sorted(kinds.items())]
        else:
            out.append((name, module.HEADER_RULE))
    return out


def said(rule, lines):
    return [sentence for _, _, sentence in fixture_headers.problems(lines, rule)]


def header_cases(label, rule, failures):
    n = 0
    for header in rule.headers:
        word = header.word
        sample = SAMPLES.get(word)
        where = "%s `// %s:`" % (label, word)
        if sample is None:
            failures.append("%s: the test has no sample line for the header" % where)
            continue
        first = (header.rows or (1,))[0]
        filler = ["// prose"] * (first - 1)
        if said(rule, filler + [sample]):
            failures.append("%s: the well-formed line %r is a failure: %r" % (where, sample, said(rule, filler + [sample])))
        # No space after the colon: no lane's pattern reads it.
        broken = sample.replace(": ", ":", 1)
        if not any("cannot read" in s for s in said(rule, filler + [broken])):
            failures.append("%s: %r draws no `cannot read` failure" % (where, broken))
        prose = "// %s the rest of a sentence" % word
        if not any("cannot read" in s for s in said(rule, filler + [prose])):
            failures.append("%s: prose %r draws no failure" % (where, prose))
        if said(rule, filler + ["// %sish layer of prose" % word]):
            failures.append("%s: a word that only starts the same draws a failure" % where)
        if said(rule, filler + ["", broken]):
            failures.append("%s: a line after the leading comment draws a failure" % where)
        if header.rows is not None:
            late = ["// prose"] * max(header.rows) + [sample]
            if not any("goes on the" in s for s in said(rule, late)):
                failures.append("%s: on row %d it draws no `goes on` failure" % (where, len(late)))
        if not header.repeat:
            twice = filler + [sample, sample]
            if not any("is stated twice" in s for s in said(rule, twice)):
                failures.append("%s: stated twice draws no `is stated twice` failure" % where)
        else:
            twice = filler + [sample, sample]
            if any("is stated twice" in s for s in said(rule, twice)):
                failures.append("%s: a header that may repeat draws a `stated twice` failure" % where)
        n += 1
    return n


def run():
    failures = []
    counts = {}
    headers = 0
    rules = lane_rules()
    for label, rule in rules:
        headers += header_cases(label, rule, failures)
    # The ordering rule, and the two multi-word spellings.
    import typecheck_lane
    late = said(typecheck_lane.HEADER_RULE, [SAMPLES["message"], SAMPLES["errors"]])
    if not any("goes before the first `// message:`" in s for s in late):
        failures.append("`// errors:` after `// message:` draws no ordering failure: %r" % late)
    toy = fixture_headers.Rule([fixture_headers.Header("stage 0", r"^// stage 0: \S", "// stage 0: REASON",
                                                       detect="stage ?0")])
    for line in ("// stage0: cannot build", "// stage 0:cannot build", "//stage 0: cannot build"):
        if not said(toy, [line]):
            failures.append("%r draws no failure under a `stage ?0` header" % line)
    if said(toy, ["// stage 0: cannot build"]):
        failures.append("a well-formed `// stage 0:` draws a failure")
    counts["fixture header words"] = headers
    counts["fixture header rules"] = len(rules)
    return failures, counts


def main():
    failures, counts = run()
    for failure in failures:
        print(failure)
    print("fixture headers: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                       ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
