#!/usr/bin/env python3
"""Compare every fresh M19 inventory candidate with the prototype renderer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory
import test_canonical


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PYTHON_DUMP = REPO / "tools/dump_ast.py"


def safe_id(relative: str, digest: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", relative).strip("-")
    return f"{stem}-{digest[:12]}"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def python_oracle(source: bytes, case_dir: Path, timeout: float
                  ) -> tuple[bytes | None, list[str]]:
    source_path = case_dir / "source.saw"
    source_path.write_bytes(source)
    argv = [sys.executable, str(PYTHON_DUMP), str(source_path)]
    write_json(case_dir / "python.argv.json", argv)
    failures: list[str] = []
    try:
        result = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        code = None
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        failures.append(f"Python oracle timed out after {timeout:g}s")
    except OSError as error:
        code, stdout, stderr = None, b"", b""
        failures.append(f"Python oracle could not launch: {error}")
    (case_dir / "python.stdout").write_bytes(stdout)
    (case_dir / "python.stderr").write_bytes(stderr)
    write_json(case_dir / "python.result.json", {"returncode": code})
    if code is not None:
        if code != 0:
            failures.append(f"Python oracle exited {code}")
        if stderr:
            failures.append("Python oracle wrote stderr")
        if not stdout.endswith(b"\n"):
            failures.append("Python oracle output lacks one final newline")
        if not stdout:
            failures.append("Python oracle output is empty")
        try:
            text = stdout.decode("utf-8")
        except UnicodeDecodeError:
            failures.append("Python oracle output is not UTF-8")
        else:
            if not text.startswith("Program {\n") or not text.endswith("\n}\n"):
                failures.append("Python oracle output is not a canonical Program record")
    if failures:
        return None, failures
    canonical = stdout[:-1]
    (case_dir / "canonical.expected").write_bytes(canonical)
    return canonical, []


def compare(binary: Path, artifacts: Path, batch_size: int, timeout: float,
            budget: int) -> tuple[dict[str, Any], list[str]]:
    fresh = inventory.build_inventory(REPO)
    if artifacts.exists() and any(artifacts.iterdir()):
        raise ValueError(f"artifact directory is not empty: {artifacts}")
    artifacts.mkdir(parents=True, exist_ok=True)
    write_json(artifacts / "inventory.json", fresh)
    rows = fresh["examples"]
    candidates = sorted((row for row in rows if row["classification"] == "candidate"),
                        key=lambda row: row["path"])
    failures: list[str] = []
    cases: list[tuple[test_canonical.CanonCase, dict[str, Any]]] = []
    case_records: list[dict[str, Any]] = []
    for row in candidates:
        relative = row["path"]
        try:
            source = (REPO / relative).read_bytes()
        except OSError as error:
            name = safe_id(relative, row["sha256"])
            case_records.append({"name": name, "path": relative, "sha256": None,
                                 "semantic_negative": bool(row["semantic_expect"]["negative"]),
                                 "oracle": "not_run", "prototype": "not_run"})
            failures.append(f"{relative}: cannot read source after inventory: {error}")
            continue
        digest = hashlib.sha256(source).hexdigest()
        name = safe_id(relative, digest)
        case_dir = artifacts / "cases" / name
        case_dir.mkdir(parents=True)
        (case_dir / "source.saw").write_bytes(source)
        record = {"name": name, "path": relative, "sha256": digest,
                  "semantic_negative": bool(row["semantic_expect"]["negative"]),
                  "oracle": "pending", "prototype": "not_run"}
        case_records.append(record)
        if digest != row["sha256"]:
            record["oracle"] = "not_run"
            failures.append(f"{relative}: source changed after inventory ({row['sha256']} -> {digest})")
            continue
        canonical, oracle_failures = python_oracle(source, case_dir, timeout)
        if oracle_failures:
            record["oracle"] = "failed"
            failures.extend(f"{relative}: {failure}" for failure in oracle_failures)
            continue
        record["oracle"] = "passed"
        case = test_canonical.CanonCase(name=name, source=source, canonical=canonical,
                                        python_oracle=False)
        cases.append((case, record))

    for offset in range(0, len(cases), batch_size):
        batch_pairs = cases[offset:offset + batch_size]
        batch = [pair[0] for pair in batch_pairs]
        batch_dir = artifacts / "batches" / f"batch-{offset // batch_size:04d}"
        try:
            data, batch_failures, _source = test_canonical.run_vm_canonical_cases(
                binary, batch, batch_dir, timeout=timeout, budget=budget)
        except Exception as error:
            message = f"prototype batch {offset // batch_size} failed: {type(error).__name__}: {error}"
            failures.append(message)
            for case, record in batch_pairs:
                record["prototype"] = "failed"
                write_json(artifacts / "cases" / case.name / "prototype.result.json",
                           {"status": "batch_failure", "message": message})
            continue
        for failure in batch_failures:
            failures.append(f"batch {offset // batch_size}: {failure}")
        try:
            results = test_canonical.parse_output(data)
        except (ValueError, UnicodeDecodeError):
            results = []
        protocol_valid = (len(results) == len(batch) and
                          all(result.case_id == index for index, result in enumerate(results)))
        if not protocol_valid:
            failures.append(f"batch {offset // batch_size}: parsed protocol records do not match batch")
        for index, (case, record) in enumerate(batch_pairs):
            case_dir = artifacts / "cases" / case.name
            if not protocol_valid:
                record["prototype"] = "failed"
                write_json(case_dir / "prototype.result.json", {"status": "malformed"})
                continue
            result = results[index]
            write_json(case_dir / "prototype.result.json",
                       {"status": result.status, "error": result.error})
            if result.canonical is not None:
                (case_dir / "canonical.actual").write_bytes(result.canonical)
            record["prototype"] = ("passed" if result.status == "OK" and
                                   result.canonical == case.canonical else "failed")
            if record["prototype"] == "failed" and not any(
                    failure.startswith(f"batch {offset // batch_size}: {case.name}:")
                    for failure in failures):
                failures.append(f"batch {offset // batch_size}: {case.name}: prototype result differs")

    classifications: dict[str, int] = dict(fresh["counts"]["by_classification"])
    summary = {
        "version": 1,
        "corpus_count": fresh["counts"]["total"],
        "candidate_count": len(candidates),
        "classifications": classifications,
        "oracle_failure_count": classifications.get("oracle_failure", 0),
        "tested_candidate_count": sum(row["prototype"] in ("passed", "failed")
                                      for row in case_records),
        "semantic_negative_candidate_count": sum(row["semantic_negative"] for row in case_records),
        "failures": failures,
        "cases": case_records,
    }
    if classifications.get("oracle_failure", 0):
        failures.append(f"inventory contains {classifications['oracle_failure']} oracle_failure row(s)")
        summary["failures"] = failures
    write_json(artifacts / "summary.json", summary)
    return summary, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--budget", type=int, default=120_000_000)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    artifacts = (args.artifacts.resolve() if args.artifacts else
                 REPO / ".build/scratch" / f"parser-examples-{time.time_ns()}")
    summary, failures = compare(args.binary.resolve(), artifacts, args.batch_size,
                                args.timeout, args.budget)
    counts = summary["classifications"]
    print(f"candidates tested: {summary['tested_candidate_count']}/{summary['candidate_count']} "
          f"(whole corpus: {summary['corpus_count']})")
    print("classifications: " + ", ".join(f"{name}={count}" for name, count in sorted(counts.items())))
    print(f"artifacts: {artifacts}")
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
