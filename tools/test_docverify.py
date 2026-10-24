#!/usr/bin/env python3
"""The docverify lane's mechanics, against sawc: the rule pin, the scaffolding
refusal, the vacuous shape, the parse-refusal fallback, and `saw-pending`'s
flip and open-issue checks.

    tools/test_docverify.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_citations  # noqa: E402
import docverify  # noqa: E402
from docverify import Block, check, classify, compile_source, vacuous  # noqa: E402

MISMATCH = 'func f() -> Int { "a" }'
ACCEPTED = "func f() -> Int { 1 }"


def block(info: str, body: str, line: int = 1) -> Block:
    return Block("test_docverify", line, info, body)


def run(info: str, body: str):
    b = block(info, body)
    return check(b, classify(b))


class Pins(unittest.TestCase):
    def test_rule_pin_matches(self):
        r = run("saw-error", "// error-rule: type.mismatch\n" + MISMATCH)
        self.assertTrue(r.ok, r.detail)

    def test_rule_and_text_pin_match(self):
        r = run("saw-error", "// error-rule: type.mismatch\n"
                "// error-contains: and found `String`\n" + MISMATCH)
        self.assertTrue(r.ok, r.detail)

    def test_wrong_rule_fails(self):
        r = run("saw-error", "// error-rule: lend.root\n" + MISMATCH)
        self.assertFalse(r.ok)
        self.assertIn("the pin is not in the diagnostics", r.detail)

    def test_wrong_text_fails(self):
        r = run("saw-error", "// error-rule: type.mismatch\n"
                "// error-contains: no such words\n" + MISMATCH)
        self.assertFalse(r.ok)

    def test_rule_line_is_mandatory(self):
        r = run("saw-error", "// error-contains: and found `String`\n" + MISMATCH)
        self.assertFalse(r.ok)
        self.assertIn("error-rule", r.detail)

    def test_accepted_error_block_fails(self):
        r = run("saw-error", "// error-rule: type.mismatch\n" + ACCEPTED)
        self.assertFalse(r.ok)
        self.assertIn("ACCEPTED", r.detail)


class Scaffolding(unittest.TestCase):
    def test_undefined_name_beside_the_pin_fails(self):
        r = run("saw-error", "// error-rule: type.mismatch\n"
                'func f() -> Int { helper()\n    "a" }')
        self.assertFalse(r.ok)
        self.assertIn("scaffolding", r.detail)

    def test_a_pinned_scaffolding_rule_is_the_subject(self):
        r = run("saw-error", "// error-rule: name.not-in-prelude\n"
                "func take(d: &Data) -> Int { d.len() }")
        self.assertTrue(r.ok, r.detail)


class Shapes(unittest.TestCase):
    def test_top_level_statement_is_vacuous(self):
        out = compile_source('let x: Int = "a"\n', "test_docverify_vacuous")
        self.assertTrue(vacuous(out))

    def test_vacuous_block_is_judged_wrapped(self):
        r = run("saw-error", '// error-rule: type.mismatch\nlet x: Int = "a"')
        self.assertTrue(r.ok, r.detail)
        self.assertEqual(r.shape, "wrapped")

    def test_parse_refusal_reads_the_parser_rule(self):
        r = run("saw-error", "// error-rule: syntax.rule.juxtaposition\n"
                "func main() {\n    let a = 3 print(a)\n}")
        self.assertTrue(r.ok, r.detail)

    def test_compiled_blocks(self):
        self.assertTrue(run("saw", ACCEPTED).ok)
        self.assertFalse(run("saw", MISMATCH).ok)
        self.assertTrue(run("saw-body", "let x = 1\nprint(x)").ok)


class Pending(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        issues = Path(self.tmp.name)
        (issues / "SL-1.md").write_text('---\n{"id":"SL-1","status":"open"}\n---\n')
        (issues / "SL-2.md").write_text('---\n{"id":"SL-2","status":"closed"}\n---\n')
        self.saved = check_citations.ISSUES_DIR
        check_citations.ISSUES_DIR = issues

    def tearDown(self):
        check_citations.ISSUES_DIR = self.saved
        self.tmp.cleanup()

    def test_still_failing_passes(self):
        self.assertTrue(run("saw-pending SL-1", MISMATCH).ok)

    def test_compiling_block_flips(self):
        r = run("saw-pending SL-1", ACCEPTED)
        self.assertFalse(r.ok)
        self.assertIn("pending, but it compiles", r.detail)

    def test_pinned_block_passes_while_the_pin_is_absent(self):
        self.assertTrue(run("saw-pending SL-1", "// error-rule: lend.root\n" + MISMATCH).ok)

    def test_pinned_block_flips_once_the_pin_appears(self):
        r = run("saw-pending SL-1", "// error-rule: type.mismatch\n" + MISMATCH)
        self.assertFalse(r.ok)
        self.assertIn("reports the pinned diagnostic", r.detail)

    def test_text_only_pin(self):
        self.assertTrue(run("saw-pending SL-1", "// error-contains: no such words\n" + MISMATCH).ok)
        self.assertFalse(run("saw-pending SL-1", "// error-contains: and found `String`\n" + MISMATCH).ok)

    def test_closed_issue_fails(self):
        r = run("saw-pending SL-2", MISMATCH)
        self.assertFalse(r.ok)
        self.assertIn("closed", r.detail)

    def test_unknown_issue_fails(self):
        r = run("saw-pending SL-3", MISMATCH)
        self.assertFalse(r.ok)
        self.assertIn("no file", r.detail)

    def test_malformed_marker_fails(self):
        r = run("saw-pending", MISMATCH)
        self.assertFalse(r.ok)
        self.assertIn("one issue id", r.detail)


if __name__ == "__main__":
    if not docverify.ensure_sawc():
        sys.exit(1)
    unittest.main()
