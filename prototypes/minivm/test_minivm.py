#!/usr/bin/env python3
"""End-to-end checks for the disposable minivm prototype."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"
# Include process startup and clang/linker work on a busy developer machine.
# The VM has an independent deterministic instruction budget for nontermination.
TIMEOUT = 30


@dataclass(frozen=True)
class RunCase:
    name: str
    stdout: str
    exit_code: int = 0
    section: str = "core"


@dataclass(frozen=True)
class RejectCase:
    name: str
    message: str
    section: str = "core"


RUN_CASES = (
    RunCase("control/static_literals", "-128\n32767\n255\n18446744073709551615\n", section="control"),
    RunCase("control/logical_loops", "0\n1\n2\n3\n9\n4\n", section="control"),
    RunCase("control/compound_rem_overflow", "runtime error: integer overflow\n", 1, "control"),
    RunCase("numbers/unary_cast_order", "-127\n18446744073709551615\n-1\n", section="numbers"),
    RunCase("numbers/unary_cast_range", "runtime error: integer cast out of range\n", 1, "numbers"),
    RunCase("numbers/unary_cast_widen", "128\n", section="numbers"),
    RunCase("numbers/complement_after_cast", "0\n", section="numbers"),
    RunCase("numbers/review_literals", "3\n1\ntrue\n-1\n18446744073709551615\n18446744073709551615\ntrue\n", section="numbers"),
    RunCase("numbers/review_unsigned", "6148914691236517205\n1\n1\n18446744073709551615\n254\n-128\n-9223372036854775808\n-9223372036854775808\n", section="numbers"),
    RunCase("numbers/overflow_u64_mul", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_u64_sub", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/shift_large_unsigned", "runtime error: shift out of range\n", 1, "numbers"),
    RunCase("arithmetic", "12\n-3\n42\n-2\n-1\n0\n"),
    RunCase("comparisons", "true\nfalse\ntrue\ntrue\ntrue\nfalse\ntrue\ntrue\n"),
    RunCase("precedence", "14\n20\n-1\ntrue\n"),
    RunCase("scopes", "9\n3\n"),
    RunCase("loop", "10\n"),
    RunCase("forward_call", "42\n"),
    RunCase("recursion", "720\n"),
    RunCase("evaluation_order", "1\n2\n3\n"),
    RunCase("void_return", "7\n8\n"),
    RunCase("if_returns", "-1\n1\n"),
    RunCase("factorial", "720\n"),
    RunCase("unreachable", "7\n"),
    RunCase("multiline_parens", "7\n"),
    RunCase("copy_independence", "4\n9\n"),
    RunCase("shadow_initializer", "6\n5\n"),
    RunCase("empty_blocks", "3\n"),
    RunCase("bool_forward", "true\nfalse\n"),
    RunCase("mutual_recursion", "true\ntrue\n"),
    RunCase("multiline_forms", "-2147483648\ntrue\n7\n13\n"),
    RunCase("overflow_add", "runtime error: integer overflow\n", 1),
    RunCase("overflow_sub", "runtime error: integer overflow\n", 1),
    RunCase("overflow_mul", "runtime error: integer overflow\n", 1),
    RunCase("overflow_neg", "runtime error: integer overflow\n", 1),
    RunCase("overflow_div", "runtime error: integer overflow\n", 1),
    RunCase("div_zero", "runtime error: division by zero\n", 1),
    RunCase("rem_zero", "runtime error: division by zero\n", 1),
    RunCase("numbers/types_and_bounds", "-128\n127\n-32768\n32767\n-2147483648\n2147483647\n-9223372036854775808\n9223372036854775807\n-9223372036854775808\n9223372036854775807\n0\n255\n0\n65535\n0\n4294967295\n0\n18446744073709551615\n0\n18446744073709551615\n", section="numbers"),
    RunCase("numbers/literals_and_aliases", "-128\n32767\n-2147483648\n9223372036854775807\n-9223372036854775808\n255\n65535\n4294967295\n18446744073709551615\n9223372036854775808\n255\n65535\n4294967295\n18446744073709551615\n42\n511\n127\n32767\n2147483647\n9223372036854775807\n-128\n2147483648\n", section="numbers"),
    RunCase("numbers/u64_calls", "18446744073709551615\n18446744073709551615\ntrue\ntrue\n", section="numbers"),
    RunCase("numbers/contextual", "-128\n65535\n15\n15\n4294967295\n", section="numbers"),
    RunCase("numbers/lossless_widening", "-12\n-12\n-12\n255\n", section="numbers"),
    RunCase("numbers/casts", "-1\n255\n255\n2147483648\n127\n", section="numbers"),
    RunCase("numbers/truncation", "255\n-1\n1\n-1\n4294967295\n-1\n18446744073709551615\n-1\n", section="numbers"),
    RunCase("numbers/byte", "255\n255\ntrue\n255\n255\n", section="numbers"),
    RunCase("numbers/wrapping", "-128\n127\n-2\n0\n255\n0\n0\n", section="numbers"),
    RunCase("numbers/bits_and_shifts", "192\n243\n90\n15\n-4\n60\n128\n240\n24\n3\n4\n", section="numbers"),
    RunCase("numbers/overflow_i64_add", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_i64_sub", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_i64_mul", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_i8_add", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_i16_sub", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_i8_mul", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_u64_add", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_u16_sub", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_u32_mul", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_neg_i64", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_neg_i8", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_div_i64", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_rem_i64", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/overflow_rem_i32", "runtime error: integer overflow\n", 1, "numbers"),
    RunCase("numbers/cast_negative_unsigned", "runtime error: integer cast out of range\n", 1, "numbers"),
    RunCase("numbers/cast_too_large", "runtime error: integer cast out of range\n", 1, "numbers"),
    RunCase("numbers/cast_unsigned_signed", "runtime error: integer cast out of range\n", 1, "numbers"),
    RunCase("numbers/shift_negative", "runtime error: shift out of range\n", 1, "numbers"),
    RunCase("numbers/shift_width", "runtime error: shift out of range\n", 1, "numbers"),
    RunCase("records/basic_reordered", "7\ntrue\n", section="records"),
    RunCase("records/evaluation_order", "2\n1\n1\n2\n", section="records"),
    RunCase("records/copy_and_assignment", "1\n9\n8\n2\n1\n2\n", section="records"),
    RunCase("records/nested_mutation", "4\n5\n9\n11\n12\n", section="records"),
    RunCase("records/call_return_mixed", "300\n-7\n18446744073709551615\n250\n-7\n18446744073709551615\n", section="records"),
    RunCase("records/one_word_result", "18446744073709551615\n", section="records"),
    RunCase("records/forward_and_numeric", "-128\n255\n65535\n", section="records"),
    RunCase("records/width_256", "0\n255\n17\n255\n", section="records"),
    RunCase("control/truth_tables", "false\nfalse\nfalse\ntrue\nfalse\ntrue\ntrue\ntrue\n", section="control"),
    RunCase("control/precedence", "true\nfalse\nfalse\ntrue\ntrue\ntrue\n", section="control"),
    RunCase("control/short_circuit_markers", "false\ntrue\n3\ntrue\n4\nfalse\n5\nfalse\n7\ntrue\n", section="control"),
    RunCase("control/short_circuit_traps", "false\ntrue\nfalse\ntrue\n", section="control"),
    RunCase("control/compound_locals", "120\n115\n230\n76\n6\n", section="control"),
    RunCase("control/compound_nested_fields", "60\n55\n165\n41\n5\n99\n", section="control"),
    RunCase("control/statics", "4294967295\n18446744073709551615\ntrue\n-9223372036854775808\n-32768\n18446744073709551614\n", section="control"),
    RunCase("control/compound_overflow", "runtime error: integer overflow\n", 1, "control"),
    RunCase("control/compound_div_zero", "runtime error: division by zero\n", 1, "control"),
)

REJECT_CASES = (
    RejectCase("control/reject_static_negative_range", "integer literal", "control"),
    RejectCase("control/reject_static_typed_narrowing", "convert", "control"),
    RejectCase("control/reject_static_function_collision", "conflicts", "control"),
    RejectCase("records/reject_builtin_name", "reserved", "records"),
    RejectCase("records/reject_record_equality", "scalar", "records"),
    RejectCase("records/reject_record_print", "print", "records"),
    RejectCase("records/reject_empty_record", "field", "records"),
    RejectCase("numbers/reject_byte_literal", "Byte", "numbers"),
    RejectCase("numbers/reject_uncontextual_u64", "integer literal", "numbers"),
    RejectCase("numbers/reject_spaced_shift", "expression", "numbers"),
    RejectCase("reject_type", "cannot implicitly convert Int to Bool"),
    RejectCase("reject_mutability", "cannot assign to immutable local"),
    RejectCase("reject_arity", "wrong number of arguments"),
    RejectCase("reject_unknown", "unknown name"),
    RejectCase("reject_duplicate", "duplicate declaration"),
    RejectCase("reject_missing_return", "may reach its end without returning"),
    RejectCase("reject_semicolon", "semicolons are not supported"),
    RejectCase("reject_string", "expected expression"),
    RejectCase("reject_bool_arithmetic", "arithmetic requires integer operands"),
    RejectCase("reject_import", "only function, record, and static declarations are supported"),
    RejectCase("reject_scope_leak", "unknown name"),
    RejectCase("reject_unary_depth", "expression nesting limit exceeded"),
    RejectCase("reject_reserved_print", "reserved"),
    RejectCase("reject_truncated", "unterminated declaration body"),
    RejectCase("reject_large_literal", "integer literal"),
    RejectCase("numbers/reject_typed_narrowing", "convert", "numbers"),
    RejectCase("numbers/reject_typed_narrowing_assignment", "convert", "numbers"),
    RejectCase("numbers/reject_typed_narrowing_argument", "convert", "numbers"),
    RejectCase("numbers/reject_typed_narrowing_return", "convert", "numbers"),
    RejectCase("numbers/reject_mixed_binary", "same type", "numbers"),
    RejectCase("numbers/reject_bool_cast", "requires integer source and target", "numbers"),
    RejectCase("numbers/reject_literal_range", "range", "numbers"),
    RejectCase("records/reject_nominal", "convert", "records"),
    RejectCase("records/reject_immutable_field", "immutable", "records"),
    RejectCase("records/reject_parameter_field", "immutable", "records"),
    RejectCase("records/reject_missing_label", "missing", "records"),
    RejectCase("records/reject_duplicate_label", "duplicate", "records"),
    RejectCase("records/reject_unknown_label", "unknown", "records"),
    RejectCase("records/reject_wrong_field_type", "convert", "records"),
    RejectCase("records/reject_direct_cycle", "recursive", "records"),
    RejectCase("records/reject_indirect_cycle", "recursive", "records"),
    RejectCase("records/reject_width_257", "256", "records"),
    RejectCase("records/reject_duplicate_record", "duplicate module name", "records"),
    RejectCase("records/reject_duplicate_field", "duplicate record field", "records"),
    RejectCase("control/reject_skipped_rhs_type", "logical operator requires Bool operands", "control"),
    RejectCase("control/reject_immutable_compound", "cannot assign to immutable local", "control"),
    RejectCase("control/reject_mixed_compound", "compound assignment operands must have the same type", "control"),
    RejectCase("control/reject_duplicate_static", "duplicate module name", "control"),
    RejectCase("control/reject_assigned_static", "cannot assign to immutable static", "control"),
    RejectCase("control/reject_dynamic_static", "unsupported static initializer", "control"),
)


def invoke(argv: list[str], timeout: int = TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)


def check_result(label: str, result: subprocess.CompletedProcess[str],
                 expected_stdout: str, expected_exit: int) -> list[str]:
    failures: list[str] = []
    if result.returncode != expected_exit:
        failures.append(f"{label}: exit {result.returncode}, expected {expected_exit}")
    if result.stdout != expected_stdout:
        failures.append(f"{label}: stdout {result.stdout!r}, expected {expected_stdout!r}")
    if result.stderr:
        failures.append(f"{label}: unexpected stderr {result.stderr!r}")
    return failures


def test_shared_case(binary: Path, clang: str, case: RunCase, temp: Path) -> list[str]:
    source = EXAMPLES / f"{case.name}.saw"
    failures = check_result(
        f"{case.name} VM", invoke([str(binary), "run", str(source)]),
        case.stdout, case.exit_code)

    emitted = invoke([str(binary), "emit-llvm", str(source)])
    if emitted.returncode != 0 or emitted.stderr:
        failures.append(
            f"{case.name} emit: exit {emitted.returncode}\n"
            f"stdout: {emitted.stdout!r}\nstderr: {emitted.stderr!r}"
        )
        return failures
    artifact_name = case.name.replace("/", "-")
    ll_path = temp / f"{artifact_name}.ll"
    ll_path.write_text(emitted.stdout, encoding="utf-8")
    for optimization in ("-O0", "-O2"):
        suffix = optimization.removeprefix("-")
        native_path = temp / f"{artifact_name}-{suffix}"
        compiled = invoke([clang, optimization, str(ll_path), "-o", str(native_path)])
        if compiled.returncode != 0:
            failures.append(
                f"{case.name} clang {optimization}: exit {compiled.returncode}\n"
                f"stdout: {compiled.stdout}\nstderr: {compiled.stderr}"
            )
            continue
        try:
            native = invoke([str(native_path)])
        except subprocess.TimeoutExpired:
            failures.append(
                f"{case.name} native {optimization}: timed out after {TIMEOUT}s")
            continue
        failures.extend(check_result(
            f"{case.name} native {optimization}", native,
            case.stdout, case.exit_code))
    return failures


def test_rejection(binary: Path, case: RejectCase) -> list[str]:
    source = EXAMPLES / f"{case.name}.saw"
    result = invoke([str(binary), "run", str(source)])
    failures: list[str] = []
    if result.returncode != 1:
        failures.append(f"{case.name}: exit {result.returncode}, expected 1")
    if result.stderr:
        failures.append(f"{case.name}: unexpected stderr {result.stderr!r}")
    located = rf"^{re.escape(str(source))}:[1-9]\d*:[1-9]\d*: "
    if not re.match(located, result.stdout):
        failures.append(f"{case.name}: diagnostic is not located: {result.stdout!r}")
    if case.message not in result.stdout:
        failures.append(f"{case.name}: missing {case.message!r}: {result.stdout!r}")
    return failures


def test_vm_limit(binary: Path, name: str, budget: int, message: str) -> list[str]:
    source = EXAMPLES / f"{name}.saw"
    result = invoke([str(binary), "run", str(source), "--budget", str(budget)])
    return check_result(name, result, message + "\n", 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=Path(".build/minivm/minivm"))
    parser.add_argument("--clang", default="clang")
    parser.add_argument(
        "--section", choices=("all", "core", "numbers", "records", "control"), default="all",
        help="run all cases or one isolated test section",
    )
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error(f"binary does not exist: {binary}")

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="minivm-test-") as directory:
        temp = Path(directory)
        run_cases = tuple(
            case for case in RUN_CASES
            if args.section == "all" or case.section == args.section
        )
        reject_cases = tuple(
            case for case in REJECT_CASES
            if args.section == "all" or case.section == args.section
        )
        for case in run_cases:
            try:
                failures.extend(test_shared_case(binary, args.clang, case, temp))
            except subprocess.TimeoutExpired:
                failures.append(f"{case.name}: timed out after {TIMEOUT}s")
        for case in reject_cases:
            try:
                failures.extend(test_rejection(binary, case))
            except subprocess.TimeoutExpired:
                failures.append(f"{case.name}: timed out after {TIMEOUT}s")
        limit_cases = () if args.section in ("numbers", "records", "control") else (
            ("budget", 20, "runtime error: instruction budget exceeded"),
            ("depth", 10_000, "runtime error: call depth exceeded"),
        )
        for name, budget, message in limit_cases:
            try:
                failures.extend(test_vm_limit(binary, name, budget, message))
            except subprocess.TimeoutExpired:
                failures.append(f"{name}: timed out after {TIMEOUT}s")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"minivm: {len(failures)} failure(s)")
        return 1
    total = len(run_cases) + len(reject_cases) + len(limit_cases)
    print(f"minivm: {total} cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
