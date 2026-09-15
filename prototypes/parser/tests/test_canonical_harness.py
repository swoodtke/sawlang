from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_canonical as canonical


def framed(case_id: int, status: str, payload: bytes | None = None,
           error: tuple[int, int, str] | None = None) -> bytes:
    data = f"CASE\n{case_id}\n{status}\n".encode()
    if status == "OK":
        assert payload is not None
        data += b"CANONICAL\n" + str(len(payload)).encode() + b"\n"
        data += b"".join(str(byte).encode() + b"\n" for byte in payload)
    else:
        assert error is not None
        line, col, message = error
        encoded = message.encode()
        data += f"LINE\n{line}\nCOL\n{col}\nMESSAGE\n{len(encoded)}\n".encode()
        data += b"".join(str(byte).encode() + b"\n" for byte in encoded)
    return data + b"END-CASE\n"


class CanonicalHarnessTests(unittest.TestCase):
    def test_framing_preserves_embedded_controls_and_multiple_records(self):
        payload = b'quote: \\"\n\x00unicode:\xc3\xa9'
        records = canonical.parse_output(framed(0, "OK", payload) + framed(
            1, "RENDER-ERROR", error=(2, 7, "bad callee")))
        self.assertEqual(records[0].canonical, payload)
        self.assertEqual(records[1].status, "RENDER-ERROR")
        self.assertEqual(records[1].error, (2, 7, "bad callee"))

    def test_parser_and_renderer_errors_are_distinct(self):
        parse = canonical.parse_output(framed(0, "PARSE-ERROR", error=(1, 2, "syntax")))[0]
        render = canonical.parse_output(framed(0, "RENDER-ERROR", error=(1, 2, "shape")))[0]
        self.assertNotEqual(parse.status, render.status)

    def test_malformed_byte_count_and_out_of_order_ids_fail(self):
        malformed = b"CASE\n0\nOK\nCANONICAL\n2\n65\nEND-CASE\n"
        with self.assertRaises(ValueError):
            canonical.parse_output(malformed)
        case = canonical.CanonCase("x", b"", canonical=b"x")
        failures = canonical.check_results([case], framed(3, "OK", b"x"))
        self.assertTrue(any("expected 0" in failure for failure in failures))

    def test_fixture_schema_is_complete_and_unique(self):
        cases = canonical.fixture_cases()
        self.assertEqual(len(cases), len({case.name for case in cases}))
        self.assertTrue(all((case.canonical is None) != (case.render_error is None)
                            for case in cases))

    def test_independently_authored_fixture_bytes_match_python_oracle_scope(self):
        cases = canonical.fixture_cases()
        with tempfile.TemporaryDirectory() as directory:
            failures, _ = canonical.check_python_oracles(
                sys.executable, cases, Path(directory), 30)
        self.assertEqual(failures, [])

    def test_wrong_status_never_counts_as_renderer_agreement(self):
        case = canonical.CanonCase("x", b"", render_error=(1, 1, "shape"),
                                   python_oracle=False)
        failures = canonical.check_results(
            [case], framed(0, "PARSE-ERROR", error=(1, 1, "shape")))
        self.assertTrue(any("expected RENDER-ERROR" in failure for failure in failures))

    def test_debt_probe_is_separate_from_passing_fixture_set(self):
        self.assertNotIn(canonical.debt_case().name,
                         {case.name for case in canonical.fixture_cases() + canonical.generated_cases()})


if __name__ == "__main__":
    unittest.main()
