import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_parser


class DecoderTests(unittest.TestCase):
    def test_byte_field_preserves_newlines_and_unicode(self):
        payload = "a\né🙂".encode()
        lines = [b"TEXT", str(len(payload)).encode(), *(str(b).encode() for b in payload)]
        cursor = test_parser.Cursor(lines)
        self.assertEqual(cursor.bytes_field("TEXT"), payload.decode())
        self.assertEqual(cursor.position, len(lines))

    def test_complete_multiple_records_do_not_split_on_end_case(self):
        def record(case_id):
            return (f"CASE\n{case_id}\nTOKEN-COUNT\n1\nOK\nROOT\n0\nNODES\n1\n"
                    "NODE\nINDEX\n0\nKIND\nProgram\nTEXT\n0\n"
                    "FIRST-CHILD\n0\nCHILD-COUNT\n0\nSTART-TOKEN\n0\nEND-TOKEN\n0\n"
                    "LINE\n1\nCOL\n1\nCHILDREN\n0\nEND-CASE\n").encode()
        parsed = test_parser.parse_output(record(0) + record(1))
        self.assertEqual([item.case_id for item in parsed], [0, 1])
        self.assertTrue(all(item.tree is not None for item in parsed))

    def test_invalid_dump_child_is_reported_without_recursive_oracle_crash(self):
        record = (b"CASE\n0\nTOKEN-COUNT\n1\nOK\nROOT\n0\nNODES\n1\n"
                  b"NODE\nINDEX\n0\nKIND\nProgram\nTEXT\n0\nFIRST-CHILD\n0\n"
                  b"CHILD-COUNT\n1\nSTART-TOKEN\n0\nEND-TOKEN\n0\nLINE\n1\nCOL\n1\n"
                  b"CHILDREN\n1\nCHILD\n9\nEND-CASE\n")
        case = test_parser.Case("bad", b"", tree={"kind": "Program", "text": "", "children": []})
        failures = test_parser.check_cases([case], record)
        self.assertTrue(any("outside node arena" in failure for failure in failures))

    def test_backward_edge_and_reachability_are_independent(self):
        nodes = [
            test_parser.Node("Identifier", "x", 0, 0, 0, 1, 1, 1),
            test_parser.Node("Program", "", 0, 1, 0, 1, 1, 1),
            test_parser.Node("Identifier", "dead", 0, 0, 0, 1, 1, 1),
        ]
        failures = test_parser.validate_tree(test_parser.Tree(1, nodes, [0]))
        self.assertTrue(any("unreachable" in failure for failure in failures))
        bad = test_parser.Tree(0, nodes[:2], [1])
        failures = test_parser.validate_tree(bad)
        self.assertTrue(any("not backward" in failure for failure in failures))

    def test_program_span_and_append_offsets_are_exact(self):
        nodes = [
            test_parser.Node("Identifier", "x", 0, 0, 0, 1, 1, 1),
            test_parser.Node("Program", "", 1, 1, 0, 1, 1, 1),
        ]
        failures = test_parser.validate_tree(test_parser.Tree(1, nodes, [0]), b"x", 3)
        self.assertTrue(any("append offset" in failure for failure in failures))
        self.assertTrue(any("Program span" in failure for failure in failures))

    def test_manifest_has_unique_names_and_independent_trees(self):
        cases = test_parser.fixture_cases()
        self.assertEqual(len({case.name for case in cases}), len(cases))
        self.assertTrue(all(case.tree is not None for case in cases))

    def test_timeout_preserves_partial_bytes_and_argv(self):
        timeout = subprocess.TimeoutExpired(["tool"], 1, output=b"partial", stderr=b"problem")
        with patch("subprocess.run", side_effect=timeout):
            with self.assertRaises(test_parser.EngineFailure) as caught:
                test_parser.run(["tool"], 1, label="probe")
        self.assertEqual(caught.exception.argv, ["tool"])
        self.assertEqual(caught.exception.stdout, b"partial")
        self.assertEqual(caught.exception.stderr, b"problem")

    def test_launcher_error_becomes_artifact_ready_failure(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("missing")):
            with self.assertRaises(test_parser.EngineFailure) as caught:
                test_parser.run(["missing"], 1, label="probe")
        self.assertIn("could not launch", str(caught.exception))
        self.assertEqual(caught.exception.argv, ["missing"])


if __name__ == "__main__":
    unittest.main()
