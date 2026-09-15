import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inventory


REPO = Path(__file__).resolve().parents[3]
COMPILER = inventory._load_compiler(REPO)


class InventoryTests(unittest.TestCase):
    def classify(self, source: bytes):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "examples/case.saw"
            path.parent.mkdir()
            path.write_bytes(source)
            return inventory.classify_file(root, "examples/case.saw", COMPILER)

    def test_semantic_negative_is_still_candidate(self):
        row = self.classify(b"// EXPECT: error\nfunc f() { 1 }\n")
        self.assertEqual(row["classification"], "candidate")
        self.assertTrue(row["semantic_expect"]["negative"])

        compile_error = self.classify(b"// EXPECT-COMPILE-ERROR: no\nfunc f() {}\n")
        self.assertEqual(compile_error["classification"], "candidate")
        self.assertTrue(compile_error["semantic_expect"]["negative"])

    def test_doc_comment_is_source_evidence_for_exclusion(self):
        row = self.classify(b"/// docs\nfunc f() {}\n")
        self.assertEqual(row["classification"], "unsupported")
        self.assertIn("documentation_comment", {item["name"] for item in row["features"]})

    def test_modifier_cannot_hide_behind_an_otherwise_admitted_ast(self):
        row = self.classify(b"public func f() {}\n")
        self.assertEqual(row["classification"], "unsupported")
        self.assertIn("visibility_modifier", {item["name"] for item in row["features"]})

    def test_initializer_equals_is_admitted_but_assignment_ast_is_not(self):
        row = self.classify(b"func f() { let x = 1\n var y = x }\n")
        self.assertEqual(row["classification"], "candidate")
        assigned = self.classify(b"func f() { let x = 1\n x = 2 }\n")
        self.assertEqual(assigned["classification"], "unsupported")
        self.assertIn("statement", {item["name"] for item in assigned["features"]})

    def test_sl73_postfix_shape_stays_unresolved(self):
        row = self.classify(b"func f() { (g)(1) }\n")
        self.assertEqual(row["classification"], "unresolved")
        self.assertIn("postfix_call_after_group_or_call", {item["name"] for item in row["features"]})

    def test_unary_complement_is_not_a_candidate(self):
        row = self.classify(b"func f() { ~1 }\n")
        self.assertEqual(row["classification"], "unsupported")
        self.assertIn("unary_operator", {item["name"] for item in row["features"]})

    def test_empty_composite_types_are_not_named_types(self):
        sources = [
            b"func f(x: ()) {}\n",
            b"func f() -> () {}\n",
            b"func f() { let x: () = g() }\n",
            b"func f(x: () -> Int) {}\n",
            b"func f() -> () -> Int {}\n",
            b"func f() { let x: () -> Int = g }\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(self.classify(source)["classification"], "unsupported")

    def test_labelled_argument_uses_value_location(self):
        Lexer, Parser, ast = COMPILER
        source = "func f() {\n  g(1)\n}\n"
        lexer = Lexer(source)
        program = Parser(lexer.tokenize(), source_file="case.saw",
                         doc_comments=lexer.doc_comments).parse()
        call = program.functions[0].body.final_expr
        call.arguments[0].name = "value"
        features, unresolved = inventory.ast_features(program, ast)
        self.assertFalse(unresolved)
        feature = next(item for item in features if item.name == "labelled_argument")
        self.assertEqual((feature.line, feature.column), (2, 5))

    def test_parse_error_is_distinct_from_unsupported(self):
        row = self.classify(b"\n\nfunc f( {\n")
        self.assertEqual(row["classification"], "parse_error")
        self.assertEqual(row["parser_verdict"], "rejected")
        self.assertEqual((row["features"][0]["line"], row["features"][0]["column"]), (3, 9))

    def test_checked_in_inventory_is_sorted_complete_and_hashed(self):
        data = inventory.decode_snapshot(json.loads(
            (REPO / "prototypes/parser/examples_inventory.json").read_text()))
        rows = data["examples"]
        paths = [row["path"] for row in rows]
        tracked = inventory.tracked_examples(REPO)
        self.assertEqual(paths, tracked)
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(data["counts"]["top"], sum(path.count("/") == 1 for path in tracked))
        self.assertEqual(data["counts"]["nested"], sum(path.count("/") > 1 for path in tracked))
        self.assertTrue(all(len(row["sha256"]) == 64 for row in rows))
        self.assertTrue(all(row["classification"] in {
            "candidate", "unsupported", "parse_error", "oracle_failure", "unresolved"
        } for row in rows))

    def test_checked_in_inventory_has_no_classification_drift(self):
        checked_in = inventory.decode_snapshot(json.loads(
            (REPO / "prototypes/parser/examples_inventory.json").read_text()))
        self.assertEqual(inventory.build_inventory(REPO), checked_in)

    def test_compact_formatter_has_one_example_per_line(self):
        row = lambda path: {"path": path, "sha256": "0" * 64, "scope": "top",
                            "classification": "candidate", "parser_verdict": "accepted",
                            "features": [], "semantic_expect": {"negative": False, "directives": []}}
        data = {"version": 1, "corpus": "test", "counts": {"total": 2},
                "examples": [row("examples/a.saw"), row("examples/b.saw")]}
        rendered = inventory.render_json(data)
        self.assertEqual(inventory.decode_snapshot(json.loads(rendered)), data)
        example_lines = rendered.splitlines()[1:-1]
        self.assertEqual(len(example_lines), 2)

    def test_snapshot_codec_round_trips_full_inventory(self):
        rich = inventory.build_inventory(REPO)
        self.assertEqual(inventory.decode_snapshot(inventory.encode_snapshot(rich)), rich)

    def test_snapshot_decoder_rejects_negative_index_and_wrong_width(self):
        rich = inventory.build_inventory(REPO)
        snapshot = inventory.encode_snapshot(rich)
        snapshot["examples"][0][2] = -1
        with self.assertRaisesRegex(ValueError, "malformed"):
            inventory.decode_snapshot(snapshot)
        snapshot = inventory.encode_snapshot(rich)
        snapshot["examples"][0].pop()
        with self.assertRaisesRegex(ValueError, "malformed"):
            inventory.decode_snapshot(snapshot)

    def test_snapshot_check_detects_missing_and_byte_drift(self):
        data = {"version": 1, "corpus": "test",
                "counts": {"total": 0, "top": 0, "nested": 0,
                "by_classification": {}, "top_by_classification": {},
                "nested_by_classification": {}}, "examples": []}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "inventory.json"
            report = Path(directory) / "inventory.md"
            self.assertFalse(inventory.snapshots_current(data, output, report))
            output.write_text(inventory.render_json(data), encoding="utf-8")
            report.write_text(inventory.report(data), encoding="utf-8")
            self.assertTrue(inventory.snapshots_current(data, output, report))
            output.write_text(output.read_text() + " ", encoding="utf-8")
            self.assertFalse(inventory.snapshots_current(data, output, report))


if __name__ == "__main__":
    unittest.main()
