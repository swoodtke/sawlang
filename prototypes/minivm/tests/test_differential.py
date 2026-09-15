import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_differential as differential
import test_minivm as regression


class ManifestTests(unittest.TestCase):
    def load(self, fixtures, registered):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps({"version": 1, "fixtures": fixtures}), encoding="utf-8")
            with patch.object(differential, "identities", return_value=registered):
                return differential.load_manifest(path)

    def test_complete_identity_is_required(self):
        _, failures = self.load([], {"run:one": object()})
        self.assertTrue(any("missing registered" in failure for failure in failures))

    def test_stale_identity_is_rejected(self):
        row = {"id": "run:gone", "classification": "agreement", "reason": "shared"}
        _, failures = self.load([row], {})
        self.assertTrue(any("stale fixtures" in failure for failure in failures))

    def test_known_difference_needs_issue_and_distinct_runtime_result(self):
        row = {"id": "run:one", "classification": "known_difference", "reason": "gap",
               "issue": "bad", "prototype": "accept", "sawc": "accept", "evidence": "marker",
               "expected_exit": 0, "expected_stdout": "same\n", "expected_stderr": ""}
        case = regression.RunCase("one", "same\n")
        _, failures = self.load([row], {"run:one": case})
        self.assertTrue(any("requires an SL issue" in failure for failure in failures))
        self.assertTrue(any("equals the registered" in failure for failure in failures))

    def test_non_object_root_and_unhashable_classification_are_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text("null", encoding="utf-8")
            _, failures = differential.load_manifest(path)
            self.assertIn("manifest: root must be an object", failures)
        row = {"id": "run:one", "classification": [], "reason": "bad"}
        _, failures = self.load([row], {"run:one": object()})
        self.assertTrue(any("invalid classification" in failure for failure in failures))

    def test_bool_is_not_an_integer_schema_value(self):
        row = {"id": "reject:one", "classification": "known_difference", "reason": "gap",
               "issue": "SL-1", "prototype": "reject", "sawc": "accept", "evidence": "x",
               "expected_exit": True, "expected_stdout": "", "expected_stderr": ""}
        _, failures = self.load([row], {"reject:one": object()})
        self.assertTrue(any("requires expected_exit" in failure for failure in failures))

    def test_duplicate_registry_identity_is_rejected(self):
        with patch.object(regression, "RUN_CASES", (regression.RunCase("same", ""),
                                                    regression.RunCase("same", ""))):
            with self.assertRaisesRegex(ValueError, "duplicate registered fixture"):
                differential.identities()

    def test_main_reports_malformed_known_row_without_crashing(self):
        row = {"id": "run:one", "classification": "known_difference", "reason": "gap",
               "prototype": "accept", "sawc": "reject", "evidence": "marker"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps({"version": 1, "fixtures": [row]}), encoding="utf-8")
            argv = ["test_differential.py", "--manifest", str(path), "--validate-only"]
            with patch.object(differential, "identities", return_value={"run:one": object()}), \
                 patch.object(sys, "argv", argv), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(differential.main(), 1)


class OutcomeTests(unittest.TestCase):
    def test_crash_is_not_a_clean_rejection(self):
        result = subprocess.CompletedProcess([], 1, "internal compiler error\n", "")
        self.assertFalse(differential.clean_rejection(result))

    def test_internal_error_with_traceback_is_not_a_known_internal_error(self):
        result = subprocess.CompletedProcess([], 1,
            "error: internal compiler error: broken\nTraceback (most recent call last):\n", "")
        self.assertFalse(differential.internal_error(result))

    def test_unexpected_agreement_fails_known_row(self):
        case = regression.RejectCase("x", "x")
        row = {"classification": "known_difference", "sawc": "accept",
               "prototype": "reject", "evidence": "stdout:"}
        compiled = subprocess.CompletedProcess([], 1, "error: x\n", "")
        failures = differential.check_sawc_expectation("reject:x", row, case, "reject", compiled, None)
        self.assertTrue(any("expected accept" in failure for failure in failures))

    def test_known_acceptance_checks_exact_output_evidence(self):
        case = regression.RejectCase("x", "x")
        row = {"classification": "known_difference", "sawc": "accept",
               "prototype": "reject", "evidence": "accepted output",
               "expected_exit": 0, "expected_stdout": "expected\n", "expected_stderr": ""}
        compiled = subprocess.CompletedProcess([], 0, "", "")
        ran = subprocess.CompletedProcess([], 0, "wrong\n", "")
        failures = differential.check_sawc_expectation("reject:x", row, case, "accept", compiled, ran)
        self.assertTrue(any("accepted outcome changed" in failure for failure in failures))

    def test_located_run_text_cannot_spoof_prototype_rejection(self):
        case = regression.RejectCase("reject_type", "cannot implicitly convert")
        source = regression.EXAMPLES / "reject_type.saw"
        run = subprocess.CompletedProcess([], 1,
            f"{source}:1:1: cannot implicitly convert\n", "")
        emit = subprocess.CompletedProcess([], 0, "valid llvm", "")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(differential, "logged_invoke", side_effect=((run, None), (emit, None))):
                failures, _ = differential.run_prototype(Path("minivm"), "clang", case, Path(directory))
        self.assertTrue(any("prototype emit did not reproduce rejection" in failure for failure in failures))

    def test_timeout_preserves_partial_byte_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "slow.py"
            script.write_text("import time\nprint('partial', flush=True)\ntime.sleep(5)\n", encoding="utf-8")
            result, error = differential.logged_invoke(
                [sys.executable, str(script)], 1, root / "timeout")
            self.assertIsNone(result)
            self.assertIn("timed out", error)
            self.assertEqual((root / "timeout.stdout").read_text(encoding="utf-8"), "partial\n")

    def test_launcher_error_is_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "missing"
            result, error = differential.logged_invoke(
                [str(Path(directory) / "does-not-exist")], 1, prefix)
            self.assertIsNone(result)
            self.assertIn("could not launch", error)
            self.assertIn("launcher_error=", prefix.with_suffix(".meta").read_text(encoding="utf-8"))

    def test_unexpected_reject_case_acceptance_is_not_executed(self):
        case = regression.RejectCase("x", "x")
        compiled = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(differential, "logged_invoke", return_value=(compiled, None)) as invoke:
            outcome, _, ran, _ = differential.sawc_outcome(
                sys.executable, Path("sawc.py"), case, Path(directory) / "output", 1,
                Path(directory), False)
        self.assertEqual(outcome, "accept")
        self.assertIsNone(ran)
        self.assertEqual(invoke.call_count, 1)

    def test_sawc_compile_removes_stale_output(self):
        case = regression.RejectCase("x", "x")
        compiled = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.write_text("stale", encoding="utf-8")
            with patch.object(differential, "logged_invoke", return_value=(compiled, None)):
                differential.sawc_outcome(sys.executable, Path("sawc.py"), case, output, 1,
                                          Path(directory), False)
            self.assertFalse(output.exists())

    def test_native_compile_removes_stale_outputs(self):
        case = regression.RunCase("x", "")
        success = subprocess.CompletedProcess([], 0, "", "")
        emitted = subprocess.CompletedProcess([], 0, "; llvm\n", "")
        calls = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for optimization in ("O0", "O2"):
                (root / f"native-{optimization}").write_text("stale", encoding="utf-8")

            def fake_invoke(argv, timeout, prefix):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return success, None
                if calls == 2:
                    return emitted, None
                self.assertFalse(Path(argv[-1]).exists())
                return subprocess.CompletedProcess([], 1, "", "compile failed"), None

            with patch.object(differential, "logged_invoke", side_effect=fake_invoke):
                differential.run_prototype(Path("minivm"), "clang", case, root)
        self.assertEqual(calls, 4)


if __name__ == "__main__":
    unittest.main()
