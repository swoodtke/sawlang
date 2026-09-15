import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import compare_examples


class CompareExamplesTests(unittest.TestCase):
    def test_python_oracle_requires_clean_exact_final_newline(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with mock.patch.object(compare_examples.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 0, b"Program {\n}\n", b"")):
                canonical, failures = compare_examples.python_oracle(b"func f() {}\n", root, 1)
            self.assertEqual(canonical, b"Program {\n}")
            self.assertEqual(failures, [])
            self.assertEqual((root / "canonical.expected").read_bytes(), b"Program {\n}")

            with mock.patch.object(compare_examples.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 0, b"UNKNOWN\tx\n", b"")):
                canonical, failures = compare_examples.python_oracle(b"", root, 1)
            self.assertIsNone(canonical)
            self.assertTrue(any("canonical Program" in failure for failure in failures))

            valid_payload = (b"Program {\n  StringLiteral(first\nERROR\tinside\n"
                             b"UNKNOWN\tinside) : String\n}\n")
            with mock.patch.object(compare_examples.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 0, valid_payload, b"")):
                canonical, failures = compare_examples.python_oracle(b"", root, 1)
            self.assertEqual(canonical, valid_payload[:-1])
            self.assertEqual(failures, [])

    def test_python_oracle_launch_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with mock.patch.object(compare_examples.subprocess, "run", side_effect=OSError("missing")):
                canonical, failures = compare_examples.python_oracle(b"", root, 1)
            self.assertIsNone(canonical)
            self.assertTrue(any("could not launch" in failure for failure in failures))
            self.assertIsNone(json.loads((root / "python.result.json").read_text())["returncode"])

    def test_fresh_hash_drift_and_oracle_failure_force_failure(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            artifacts = root / "artifacts"
            (repo / "examples").mkdir(parents=True)
            source = b"func f() {}\n"
            (repo / "examples/case.saw").write_bytes(source)
            inventory_data = {
                "counts": {"total": 2, "by_classification": {"candidate": 1, "oracle_failure": 1}},
                "examples": [{"path": "examples/case.saw", "classification": "candidate",
                              "sha256": "0" * 64,
                              "semantic_expect": {"negative": True, "directives": []}}],
            }
            with (mock.patch.object(compare_examples, "REPO", repo),
                  mock.patch.object(compare_examples.inventory, "build_inventory", return_value=inventory_data),
                  mock.patch.object(compare_examples, "python_oracle") as oracle,
                  mock.patch.object(compare_examples.test_canonical, "run_vm_canonical_cases") as vm):
                summary, failures = compare_examples.compare(Path("vm"), artifacts, 10, 1, 10)
            oracle.assert_not_called()
            vm.assert_not_called()
            self.assertEqual(summary["candidate_count"], 1)
            self.assertEqual(summary["semantic_negative_candidate_count"], 1)
            self.assertTrue(any("source changed after inventory" in item for item in failures))
            self.assertTrue(any("oracle_failure row" in item for item in failures))
            persisted = json.loads((artifacts / "summary.json").read_text())
            self.assertEqual(persisted["failures"], failures)

    def test_batches_continue_after_independent_prototype_failure(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            artifacts = root / "artifacts"
            (repo / "examples").mkdir(parents=True)
            rows = []
            for name in ("a", "b"):
                source = f"func {name}() {{}}\n".encode()
                (repo / f"examples/{name}.saw").write_bytes(source)
                rows.append({"path": f"examples/{name}.saw", "classification": "candidate",
                             "sha256": hashlib.sha256(source).hexdigest(),
                             "semantic_expect": {"negative": False, "directives": []}})
            inventory_data = {"counts": {"total": 2, "by_classification": {"candidate": 2}},
                              "examples": list(reversed(rows))}
            calls = []
            def run_vm(_binary, cases, workspace, **_kwargs):
                calls.append([case.name for case in cases])
                if len(calls) == 1:
                    raise RuntimeError("boom")
                data = (b"CASE\n0\nOK\nCANONICAL\n4\n116\n114\n101\n101\nEND-CASE\n")
                return data, [], workspace / "canonical-batch.saw"
            with (mock.patch.object(compare_examples, "REPO", repo),
                  mock.patch.object(compare_examples.inventory, "build_inventory", return_value=inventory_data),
                  mock.patch.object(compare_examples, "python_oracle", return_value=(b"tree", [])),
                  mock.patch.object(compare_examples.test_canonical, "run_vm_canonical_cases", side_effect=run_vm)):
                summary, failures = compare_examples.compare(Path("vm"), artifacts, 1, 1, 10)
            self.assertEqual(len(calls), 2)
            self.assertTrue(any("prototype batch 0 failed" in item for item in failures))
            self.assertEqual([row["path"] for row in summary["cases"]],
                             ["examples/a.saw", "examples/b.saw"])
            self.assertEqual([row["prototype"] for row in summary["cases"]], ["failed", "passed"])

    def test_malformed_batch_marks_every_case_failed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            artifacts = root / "artifacts"
            (repo / "examples").mkdir(parents=True)
            source = b"func a() {}\n"
            (repo / "examples/a.saw").write_bytes(source)
            rows = [{"path": "examples/a.saw", "classification": "candidate",
                     "sha256": hashlib.sha256(source).hexdigest(),
                     "semantic_expect": {"negative": False, "directives": []}}]
            data = {"counts": {"total": 1, "by_classification": {"candidate": 1}},
                    "examples": rows}
            with (mock.patch.object(compare_examples, "REPO", repo),
                  mock.patch.object(compare_examples.inventory, "build_inventory", return_value=data),
                  mock.patch.object(compare_examples, "python_oracle", return_value=(b"tree", [])),
                  mock.patch.object(compare_examples.test_canonical, "run_vm_canonical_cases",
                                    return_value=(b"garbage", ["malformed canonical protocol"], Path("x")))):
                summary, failures = compare_examples.compare(Path("vm"), artifacts, 10, 1, 10)
            self.assertEqual(summary["cases"][0]["prototype"], "failed")
            self.assertTrue(failures)


if __name__ == "__main__":
    unittest.main()
