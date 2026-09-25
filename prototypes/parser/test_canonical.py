#!/usr/bin/env python3
"""Byte-exact M19 canonical renderer contract across Saw execution engines."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_parser as arena


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LEXER = REPO / "compiler/lex/src/lib.saw"
PARSER = HERE / "src/lib.saw"
CANONICAL = HERE / "src/canonical.saw"
DRIVER = HERE / "canonical_driver.saw"
FIXTURES = HERE / "fixtures/canonical_cases.json"
PYTHON_DUMP = REPO / "tools/dump_ast.py"


@dataclass(frozen=True)
class CanonCase:
    name: str
    source: bytes
    canonical: bytes | None = None
    render_error: tuple[int, int, str] | None = None
    python_oracle: bool = True


@dataclass(frozen=True)
class CanonResult:
    case_id: int
    status: str
    canonical: bytes | None = None
    error: tuple[int, int, str] | None = None


def fixture_cases() -> list[CanonCase]:
    raw = json.loads(FIXTURES.read_text(encoding="utf-8"))
    if type(raw) is not dict or raw.get("version") != 1 or type(raw.get("cases")) is not list:
        raise ValueError("canonical fixtures require version 1 and a cases array")
    cases: list[CanonCase] = []
    names: set[str] = set()
    for row in raw["cases"]:
        if type(row) is not dict or type(row.get("name")) is not str or row["name"] in names:
            raise ValueError("canonical fixture names must be unique strings")
        if type(row.get("source")) is not str or type(row.get("python_oracle")) is not bool:
            raise ValueError(f"{row.get('name')}: source and python_oracle required")
        canonical = row.get("canonical")
        error = row.get("render_error")
        if (type(canonical) is str) == (type(error) is dict):
            raise ValueError(f"{row['name']}: exactly one canonical or render_error required")
        render_error = None
        if type(error) is dict:
            if (type(error.get("line")) is not int or type(error.get("col")) is not int or
                    type(error.get("message")) is not str):
                raise ValueError(f"{row['name']}: malformed render_error")
            render_error = (error["line"], error["col"], error["message"])
        names.add(row["name"])
        cases.append(CanonCase(row["name"], row["source"].encode(),
                               canonical.encode() if type(canonical) is str else None,
                               render_error, row["python_oracle"]))
    return cases


def indent(lines: list[str], amount: int = 1) -> list[str]:
    prefix = "  " * amount
    return [prefix + line for line in lines]


def program_with_expression(name: str, expression: list[str]) -> bytes:
    lines = ["Program {", "  functions: [", f"    Function {name}() -> Int {{",
             "      final_expr:", *indent(expression, 4), "    }", "  ]", "}"]
    return "\n".join(lines).encode()


def program_with_assignment(name: str, value: list[str], operator: str = "") -> bytes:
    statement = "AssignStatement" if not operator else f"CompoundAssignStatement {operator}"
    lines = ["Program {", "  functions: [", f"    Function {name}() -> Void {{",
             f"      {statement}", "        target:", "          Identifier(x)",
             "        value:", *indent(value, 5), "    }", "  ]", "}"]
    return "\n".join(lines).encode()


def generated_cases() -> list[CanonCase]:
    unary = ["IntLiteral(1) : Int"]
    for _ in range(256):
        unary = ["UnaryOp(-)", *indent(unary)]
    call = ["IntLiteral(1) : Int"]
    for _ in range(256):
        call = ["FunctionCall f()", "  arg[0]: ", *indent(call, 2)]
    chain = ["IntLiteral(0) : Int"]
    for value in range(1, 301):
        chain = ["BinaryOp(+)", "  left:", *indent(chain, 2), "  right:",
                 f"    IntLiteral({value}) : Int"]
    assignment_chain = ["IntLiteral(0) : Int"]
    for value in range(1, 301):
        assignment_chain = ["BinaryOp(+)", "  left:", *indent(assignment_chain, 2),
                            "  right:", f"    IntLiteral({value}) : Int"]
    return [
        CanonCase("authored-depth-groups-256",
                  ("func groups() -> Int { " + "(" * 256 + "1" + ")" * 256 + " }\n").encode(),
                  program_with_expression("groups", ["IntLiteral(1) : Int"]), python_oracle=False),
        CanonCase("authored-depth-unary-256",
                  ("func unary() -> Int { " + "-" * 256 + "1 }\n").encode(),
                  program_with_expression("unary", unary), python_oracle=False),
        CanonCase("authored-depth-call-256",
                  ("func calls() -> Int { " + "f(" * 256 + "1" + ")" * 256 + " }\n").encode(),
                  program_with_expression("calls", call), python_oracle=False),
        CanonCase("authored-long-left-chain",
                  ("func chain() -> Int { " + " + ".join(str(i) for i in range(301)) + " }\n").encode(),
                  program_with_expression("chain", chain), python_oracle=False),
        CanonCase("authored-assignment-target-groups-256",
                  ("func target() { " + "(" * 256 + "x" + ")" * 256 + " = 1 }\n").encode(),
                  program_with_assignment("target", ["IntLiteral(1) : Int"]),
                  python_oracle=False),
        CanonCase("authored-assignment-rhs-groups-256",
                  ("func rhs() { x = " + "(" * 256 + "1" + ")" * 256 + " }\n").encode(),
                  program_with_assignment("rhs", ["IntLiteral(1) : Int"]),
                  python_oracle=False),
        CanonCase("authored-assignment-long-shallow-rhs",
                  ("func assigned_chain() { x = " +
                   " + ".join(str(i) for i in range(301)) + " }\n").encode(),
                  program_with_assignment("assigned_chain", assignment_chain),
                  python_oracle=False),
    ]


def debt_case() -> CanonCase:
    return CanonCase("sl73-grouped-identifier-callee", b"func use() -> Int { (f)(1) }\n",
                     b"Program {\n  functions: [\n    Function use() -> Int {\n      final_expr:\n"
                     b"        FunctionCall f()\n          arg[0]: \n            IntLiteral(1) : Int\n"
                     b"    }\n  ]\n}", python_oracle=True)


def assembled_source(cases: list[CanonCase]) -> bytes:
    parts = [LEXER.read_text(), "\n", PARSER.read_text(), "\n", CANONICAL.read_text(),
             "\n", DRIVER.read_text(), "\nfunc main() {\n"]
    for case_id, case in enumerate(cases):
        parts.append("    if true {\n        var b = StringBuilder()\n")
        for statement in arena.saw_string_chunks(case.source):
            parts.append(f"        {statement}\n")
        parts.append(f"        dump_canonical_case({case_id}, b.build())\n    }}\n")
    parts.append("}\n")
    return "".join(parts).encode()


def parse_record(data: bytes) -> CanonResult:
    cursor = arena.Cursor(data.splitlines())
    case_id = cursor.integer("CASE")
    status = cursor.take().decode()
    if status == "OK":
        canonical = cursor.bytes_field("CANONICAL").encode()
        cursor.take("END-CASE")
        result = CanonResult(case_id, status, canonical=canonical)
    elif status in ("PARSE-ERROR", "RENDER-ERROR"):
        error = (cursor.integer("LINE"), cursor.integer("COL"), cursor.bytes_field("MESSAGE"))
        cursor.take("END-CASE")
        result = CanonResult(case_id, status, error=error)
    else:
        raise ValueError(f"unknown canonical status {status!r}")
    if cursor.position != len(cursor.lines):
        raise ValueError("trailing canonical record data")
    return result


def parse_output(data: bytes) -> list[CanonResult]:
    marker = b"CASE\n"
    if data and not data.startswith(marker):
        raise ValueError("canonical protocol lacks initial CASE marker")
    records: list[bytes] = []
    current = bytearray()
    for line in data.splitlines(keepends=True):
        if line == marker and current:
            records.append(bytes(current))
            current.clear()
        current.extend(line)
    if current:
        records.append(bytes(current))
    return [parse_record(record) for record in records]


def check_results(cases: list[CanonCase], data: bytes) -> list[str]:
    try:
        results = parse_output(data)
    except (ValueError, UnicodeDecodeError) as error:
        return [f"malformed canonical protocol: {error}"]
    if len(results) != len(cases):
        return [f"expected {len(cases)} records, got {len(results)}"]
    failures: list[str] = []
    for index, (case, result) in enumerate(zip(cases, results)):
        if result.case_id != index:
            failures.append(f"{case.name}: id {result.case_id}, expected {index}")
        if case.canonical is not None:
            if result.status != "OK":
                failures.append(f"{case.name}: expected OK, got {result.status} {result.error!r}")
            elif result.canonical != case.canonical:
                failures.append(f"{case.name}: canonical bytes differ")
        elif result.status != "RENDER-ERROR":
            failures.append(f"{case.name}: expected RENDER-ERROR, got {result.status}")
        elif result.error != case.render_error:
            failures.append(f"{case.name}: renderer error {result.error!r}, expected {case.render_error!r}")
    return failures


def python_dump(python: str, case: CanonCase, root: Path, timeout: float) -> tuple[int, bytes, bytes, list[str]]:
    source = root / f"{case.name}.saw"
    source.write_bytes(case.source)
    argv = [python, str(PYTHON_DUMP), str(source)]
    result = arena.run(argv, timeout, label=f"python oracle {case.name}")
    return result.returncode, result.stdout, result.stderr, argv


def check_python_oracles(python: str, cases: list[CanonCase], root: Path,
                         timeout: float) -> tuple[list[str], list[tuple[str, list[str], int, bytes, bytes]]]:
    failures: list[str] = []
    logs = []
    for case in cases:
        if not case.python_oracle or case.canonical is None:
            continue
        code, stdout, stderr, argv = python_dump(python, case, root, timeout)
        logs.append((case.name, argv, code, stdout, stderr))
        expected = case.canonical + b"\n"
        if code != 0 or stderr or stdout != expected:
            failures.append(f"{case.name}: Python parse-only oracle differs")
    return failures, logs


def run_vm_canonical_cases(binary: Path, cases: list[CanonCase], workspace: Path,
                           timeout: float = 300, budget: int = 120_000_000
                           ) -> tuple[bytes, list[str], Path]:
    """Run an arbitrary audited canonical batch through the VM protocol."""
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "canonical-batch.saw"
    source.write_bytes(assembled_source(cases))
    argv = [str(binary.resolve()), "run", str(source), "--budget", str(budget)]
    (workspace / "vm.argv.json").write_text(json.dumps(argv, indent=2) + "\n")
    try:
        data = arena.output("canonical VM batch", argv, timeout)
    except arena.EngineFailure as error:
        (workspace / "vm.stdout").write_bytes(error.stdout)
        (workspace / "vm.stderr").write_bytes(error.stderr)
        raise
    (workspace / "vm.stdout").write_bytes(data)
    (workspace / "vm.stderr").write_bytes(b"")
    return data, check_results(cases, data), source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--sawc", type=Path, default=REPO / "sawc/sawc.py")
    parser.add_argument("--sawc-python", default=sys.executable)
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--compile-timeout", type=float, default=600)
    parser.add_argument("--no-asan", action="store_true")
    parser.add_argument("--debt-probe", action="store_true")
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    cases = [debt_case()] if args.debt_probe else fixture_cases() + generated_cases()
    artifact = (args.artifacts.resolve() if args.artifacts else
                REPO / ".build/scratch" / f"canonical-{time.time_ns()}")
    artifact.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    outputs: dict[str, bytes] = {}
    logs: list[tuple[str, list[str], int, bytes, bytes]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="m19-canonical-") as raw_temp:
            temp = Path(raw_temp)
            source = temp / "canonical-contract.saw"
            source.write_bytes(assembled_source(cases))
            (artifact / "source.saw").write_bytes(source.read_bytes())
            vm_argv = [str(args.binary.resolve()), "run", str(source), "--budget", "120000000"]
            vm = arena.output("VM", vm_argv, args.timeout)
            outputs["VM"] = vm
            logs.append(("VM", vm_argv, 0, vm, b""))
            emit_argv = [str(args.binary.resolve()), "emit-llvm", str(source)]
            emitted = arena.output("emit", emit_argv, args.compile_timeout)
            logs.append(("emit", emit_argv, 0, emitted, b""))
            (artifact / "program.ll").write_bytes(emitted)
            modes = [("O0", ["-O0"]), ("O2", ["-O2"])]
            if not args.no_asan:
                modes.append(("ASan", ["-O1", "-fsanitize=address"]))
            for name, flags in modes:
                executable = temp / name
                compile_argv = [args.clang, *flags, str(artifact / "program.ll"), "-o", str(executable)]
                compiled = arena.run(compile_argv, args.compile_timeout, label=f"clang {name}")
                logs.append((f"clang-{name}", compile_argv, compiled.returncode,
                             compiled.stdout, compiled.stderr))
                if compiled.returncode != 0:
                    raise arena.EngineFailure(f"clang {name}", compile_argv,
                                              f"exit {compiled.returncode}", compiled.stdout, compiled.stderr)
                run_argv = [str(executable)]
                outputs[name] = arena.output(name, run_argv, args.timeout)
                logs.append((name, run_argv, 0, outputs[name], b""))
            sawc_executable = temp / "sawc"
            sawc_argv = [args.sawc_python, str(args.sawc.resolve()), str(source), "-o", str(sawc_executable)]
            compiled = arena.run(sawc_argv, args.compile_timeout, label="sawc compile")
            logs.append(("sawc-compile", sawc_argv, compiled.returncode, compiled.stdout, compiled.stderr))
            if compiled.returncode != 0:
                raise arena.EngineFailure("sawc compile", sawc_argv, f"exit {compiled.returncode}",
                                          compiled.stdout, compiled.stderr)
            sawc_run_argv = [str(sawc_executable)]
            outputs["sawc"] = arena.output("sawc", sawc_run_argv, args.timeout)
            logs.append(("sawc-run", sawc_run_argv, 0, outputs["sawc"], b""))
            for engine, data in outputs.items():
                failures.extend(f"{engine}: {failure}" for failure in check_results(cases, data))
                if data != vm:
                    failures.append(f"{engine}: complete framed output differs from VM")
            if not args.debt_probe:
                oracle_failures, oracle_logs = check_python_oracles(
                    args.sawc_python, cases, temp, args.timeout)
                failures.extend(oracle_failures)
                logs.extend(oracle_logs)
                arena_cases = [arena.Case(case.name, case.source) for case in cases]
                arena_workspace = artifact / "arena"
                arena_source = arena_workspace / "arena-contract.saw"
                arena_workspace.mkdir(parents=True, exist_ok=True)
                arena_source.write_bytes(arena.assembled_source(arena_cases))
                arena_argv = [str(args.binary.resolve()), "run", str(arena_source),
                              "--budget", "120000000"]
                (arena_workspace / "vm.argv.json").write_text(json.dumps(arena_argv, indent=2) + "\n")
                arena_data = arena.output("arena VM", arena_argv, args.timeout)
                (arena_workspace / "vm.stdout").write_bytes(arena_data)
                (arena_workspace / "vm.stderr").write_bytes(b"")
                failures.extend(f"arena: {failure}" for failure in arena.check_cases(arena_cases, arena_data))
            else:
                code, python_data, python_stderr, argv = python_dump(
                    args.sawc_python, cases[0], temp, args.timeout)
                logs.append(("SL-73-python", argv, code, python_data, python_stderr))
                if code != 0 or python_stderr or python_data != cases[0].canonical + b"\n":
                    failures.append("SL-73 diagnostic debt remains: Python parse-only oracle rejects or differs")
    except (arena.EngineFailure, subprocess.TimeoutExpired) as error:
        failures.append(str(error))
        if isinstance(error, arena.EngineFailure):
            logs.append(("failure", error.argv, -999, error.stdout, error.stderr))
    for engine, data in outputs.items():
        (artifact / f"{engine}.out").write_bytes(data)
    for index, (label, argv, code, stdout, stderr) in enumerate(logs):
        stem = artifact / f"command-{index:03d}-{label}"
        stem.with_suffix(".json").write_text(json.dumps({"argv": argv, "exit": code}, indent=2) + "\n")
        stem.with_suffix(".stdout").write_bytes(stdout)
        stem.with_suffix(".stderr").write_bytes(stderr)
    if failures:
        (artifact / "failures.txt").write_text("\n".join(failures) + "\n")
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"artifacts: {artifact}")
        return 1
    oracle_count = sum(case.python_oracle and case.canonical is not None for case in cases)
    print(f"canonical parser: {len(cases)} cases passed; Python parse-only compared {oracle_count}; "
          "engines=[VM, O0, O2" + ("" if args.no_asan else ", ASan") +
          ", sawc, arena VM]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
