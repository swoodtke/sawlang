#!/usr/bin/env python3
"""Auditable same-source agreement guard for every registered minivm fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import test_minivm as regression


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
MANIFEST = ROOT / "differential_manifest.json"
KINDS = {"agreement", "known_difference", "subset_exclusion"}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def identities() -> dict[str, object]:
    result: dict[str, object] = {}
    for case in regression.RUN_CASES:
        identity = f"run:{case.name}"
        if identity in result:
            raise ValueError(f"duplicate registered fixture: {identity}")
        result[identity] = case
    for case in regression.REJECT_CASES:
        identity = f"reject:{case.name}"
        if identity in result:
            raise ValueError(f"duplicate registered fixture: {identity}")
        result[identity] = case
    return result


def load_manifest(path: Path = MANIFEST) -> tuple[dict[str, dict[str, object]], list[str]]:
    failures: list[str] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {}, [f"manifest: {error}"]
    if not isinstance(raw, dict):
        return {}, ["manifest: root must be an object"]
    if type(raw.get("version")) is not int or raw.get("version") != 1 or not isinstance(raw.get("fixtures"), list):
        return {}, ["manifest: expected version 1 and a fixtures array"]
    rows: dict[str, dict[str, object]] = {}
    for number, row in enumerate(raw["fixtures"], 1):
        if not isinstance(row, dict):
            failures.append(f"manifest row {number}: expected object")
            continue
        identity = row.get("id")
        classification = row.get("classification")
        reason = row.get("reason")
        if not isinstance(identity, str) or identity in rows:
            failures.append(f"manifest row {number}: missing or duplicate id")
            continue
        if not isinstance(classification, str) or classification not in KINDS:
            failures.append(f"{identity}: invalid classification {classification!r}")
        if not isinstance(reason, str) or not reason.strip():
            failures.append(f"{identity}: nonempty reason required")
        allowed = {"id", "classification", "reason", "issue", "prototype", "sawc", "evidence",
                   "expected_exit", "expected_stdout", "expected_stderr", "expected_errors"}
        extra = set(row) - allowed
        if extra:
            failures.append(f"{identity}: unknown fields {sorted(extra)}")
        if classification == "known_difference":
            if not re.fullmatch(r"SL-[1-9][0-9]*", str(row.get("issue", ""))):
                failures.append(f"{identity}: known difference requires an SL issue")
            if row.get("prototype") not in ("accept", "reject") or row.get("sawc") not in ("accept", "reject", "internal_error"):
                failures.append(f"{identity}: known difference requires explicit outcomes")
            if not isinstance(row.get("evidence"), str) or not row["evidence"]:
                failures.append(f"{identity}: known difference requires evidence")
            if row.get("sawc") == "accept":
                if type(row.get("expected_exit")) is not int:
                    failures.append(f"{identity}: known sawc acceptance requires expected_exit")
                for field in ("expected_stdout", "expected_stderr"):
                    if not isinstance(row.get(field), str):
                        failures.append(f"{identity}: known sawc acceptance requires {field}")
            elif row.get("sawc") == "reject" and (
                    type(row.get("expected_errors")) is not int or row.get("expected_errors", 0) <= 0):
                failures.append(f"{identity}: known sawc rejection requires positive expected_errors")
        rows[identity] = row
    try:
        registered = identities()
    except ValueError as error:
        return rows, [str(error)]
    missing = sorted(set(registered) - set(rows))
    stale = sorted(set(rows) - set(registered))
    if missing:
        failures.append("manifest missing registered fixtures: " + ", ".join(missing))
    if stale:
        failures.append("manifest has stale fixtures: " + ", ".join(stale))
    for identity in set(rows) & set(registered):
        row = rows[identity]
        if row.get("classification") == "known_difference":
            registry_outcome = "accept" if identity.startswith("run:") else "reject"
            if row.get("prototype") != registry_outcome:
                failures.append(f"{identity}: prototype outcome contradicts registry kind")
            if row.get("sawc") == registry_outcome:
                if registry_outcome != "accept":
                    failures.append(f"{identity}: reject/reject is not a known runtime difference")
                else:
                    case = registered[identity]
                    expected = (row.get("expected_exit"), row.get("expected_stdout"), row.get("expected_stderr"))
                    if expected == (case.exit_code, case.stdout, ""):
                        failures.append(f"{identity}: known accepted outcome equals the registered prototype outcome")
    return rows, failures


def issue_failure(issue: str) -> str | None:
    path = REPO / ".sawtracker" / "issues" / f"{issue}.md"
    if not path.is_file():
        return f"{issue}: local tracker state missing"
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        metadata = json.loads(lines[1])
    except (IndexError, json.JSONDecodeError) as error:
        return f"{issue}: unreadable local tracker metadata: {error}"
    if metadata.get("status") == "closed" or metadata.get("stage") == "closed":
        return f"{issue}: known difference cites a closed issue"
    return None


def invoke(argv: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)


def clean_rejection(result: subprocess.CompletedProcess[str]) -> bool:
    diagnostic = ANSI.sub("", result.stdout + result.stderr).lower()
    error_count = len(re.findall(r"^error(?:\[[^]]+\])?:", diagnostic, re.MULTILINE))
    return (result.returncode == 1 and error_count >= 1 and "traceback" not in diagnostic
            and "internal compiler error" not in diagnostic and "killed:" not in diagnostic)


def internal_error(result: subprocess.CompletedProcess[str]) -> bool:
    diagnostic = ANSI.sub("", result.stdout + result.stderr).lower()
    internal_count = len(re.findall(r"^error: internal compiler error", diagnostic, re.MULTILINE))
    return (result.returncode == 1 and internal_count == 1 and "traceback" not in diagnostic
            and "killed:" not in diagnostic)


def sawc_outcome(python: str, sawc: Path, case: object, output: Path, timeout: int,
                 artifacts: Path, run_accepted: bool) -> tuple[str, subprocess.CompletedProcess[str] | None, subprocess.CompletedProcess[str] | None, str | None]:
    source = regression.EXAMPLES / f"{case.name}.saw"
    output.unlink(missing_ok=True)
    compiled, error = logged_invoke([python, str(sawc), str(source), "-o", str(output)],
                                    timeout, artifacts / "sawc-compile")
    if error or compiled is None:
        return "timeout", compiled, None, error
    if compiled.returncode != 0:
        if clean_rejection(compiled):
            outcome = "reject"
        elif internal_error(compiled):
            outcome = "internal_error"
        else:
            outcome = "invalid_failure"
        return outcome, compiled, None, None
    if not run_accepted:
        return "accept", compiled, None, None
    ran, error = logged_invoke([str(output)], regression.TIMEOUT, artifacts / "sawc-run")
    if error or ran is None:
        return "timeout", compiled, ran, error
    return "accept", compiled, ran, None


def logged_invoke(argv: list[str], timeout: int, prefix: Path) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
    def decoded(value: str | bytes | None) -> str:
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")

    try:
        result = invoke(argv, timeout)
    except subprocess.TimeoutExpired as error:
        prefix.with_suffix(".stdout").write_text(decoded(error.stdout), encoding="utf-8")
        prefix.with_suffix(".stderr").write_text(decoded(error.stderr), encoding="utf-8")
        prefix.with_suffix(".meta").write_text(f"timeout={timeout}\nargv={argv!r}\n", encoding="utf-8")
        return None, f"timed out after {timeout}s"
    except OSError as error:
        prefix.with_suffix(".stdout").write_text("", encoding="utf-8")
        prefix.with_suffix(".stderr").write_text(str(error) + "\n", encoding="utf-8")
        prefix.with_suffix(".meta").write_text(
            f"launcher_error={type(error).__name__}: {error}\nargv={argv!r}\n", encoding="utf-8")
        return None, f"could not launch: {error}"
    prefix.with_suffix(".stdout").write_text(result.stdout, encoding="utf-8")
    prefix.with_suffix(".stderr").write_text(result.stderr, encoding="utf-8")
    prefix.with_suffix(".meta").write_text(f"exit={result.returncode}\nargv={argv!r}\n", encoding="utf-8")
    return result, None


def run_prototype(binary: Path, clang: str, case: object, temp: Path) -> tuple[list[str], dict[str, int]]:
    failures: list[str] = []
    source = regression.EXAMPLES / f"{case.name}.saw"
    run, error = logged_invoke([str(binary), "run", str(source)], regression.TIMEOUT, temp / "prototype-run")
    engines = {"prototype_vm": 1, "prototype_emit": 0, "clang": 0, "native": 0}
    if error:
        failures.append(f"prototype run {error}")
    elif isinstance(case, regression.RunCase):
        failures.extend(regression.check_result("prototype VM", run, case.stdout, case.exit_code))
    else:
        if run.returncode != 1 or run.stderr:
            failures.append(f"prototype run rejection shape changed: exit {run.returncode}, stderr={run.stderr!r}")
        located = rf"^{re.escape(str(source))}:[1-9]\d*:[1-9]\d*: "
        if not re.match(located, run.stdout) or case.message not in run.stdout:
            failures.append(f"prototype run missing located diagnostic {case.message!r}: {run.stdout!r}")
    emitted, error = logged_invoke([str(binary), "emit-llvm", str(source)], regression.TIMEOUT,
                                   temp / "prototype-emit")
    engines["prototype_emit"] += 1
    if isinstance(case, regression.RejectCase):
        if error:
            failures.append(f"prototype emit {error}")
        elif emitted.returncode != 1 or emitted.stderr or case.message not in emitted.stdout:
            failures.append(f"prototype emit did not reproduce rejection {case.message!r}: exit {emitted.returncode}, stdout={emitted.stdout!r}, stderr={emitted.stderr!r}")
        return failures, engines
    if error or emitted is None or emitted.returncode != 0 or emitted.stderr:
        failures.append(f"prototype emit failed: {error or ('exit ' + str(emitted.returncode))}")
        return failures, engines
    ll_path = temp / "program.ll"
    ll_path.write_text(emitted.stdout, encoding="utf-8")
    for optimization in ("O0", "O2"):
        native = temp / f"native-{optimization}"
        native.unlink(missing_ok=True)
        compiled, error = logged_invoke([clang, f"-{optimization}", str(ll_path), "-o", str(native)],
                                        regression.TIMEOUT, temp / f"clang-{optimization}")
        engines["clang"] += 1
        if error or compiled is None or compiled.returncode != 0:
            failures.append(f"clang {optimization} failed: {error or ('exit ' + str(compiled.returncode))}")
            continue
        ran, error = logged_invoke([str(native)], regression.TIMEOUT, temp / f"native-run-{optimization}")
        engines["native"] += 1
        if error:
            failures.append(f"native {optimization} {error}")
        else:
            failures.extend(regression.check_result(f"native {optimization}", ran, case.stdout, case.exit_code))
    return failures, engines


def check_sawc_expectation(identity: str, row: dict[str, object], case: object, outcome: str,
                           compiled: subprocess.CompletedProcess[str],
                           ran: subprocess.CompletedProcess[str] | None) -> list[str]:
    classification = str(row["classification"])
    expected = "accept" if isinstance(case, regression.RunCase) else "reject"
    if classification == "known_difference":
        expected = str(row["sawc"])
    if outcome != expected:
        return [f"{identity}: sawc outcome {outcome}, expected {expected}"]
    failures: list[str] = []
    evidence = str(row.get("evidence", ""))
    if classification == "known_difference":
        if expected == "accept":
            if ran is None:
                failures.append(f"{identity}: sawc accepted but did not run")
            else:
                expected_exit = int(row["expected_exit"])
                expected_stdout = str(row["expected_stdout"])
                expected_stderr = str(row["expected_stderr"])
                if (ran.returncode, ran.stdout, ran.stderr) != (expected_exit, expected_stdout, expected_stderr):
                    failures.append(f"{identity}: sawc accepted outcome changed: exit={ran.returncode} stdout={ran.stdout!r} stderr={ran.stderr!r}")
        elif expected == "reject":
            diagnostic = ANSI.sub("", compiled.stdout + compiled.stderr).lower()
            if evidence.lower() not in diagnostic:
                failures.append(f"{identity}: missing known evidence {evidence!r}")
            error_count = len(re.findall(r"^error(?:\[[^]]+\])?:", diagnostic, re.MULTILINE))
            if error_count != int(row["expected_errors"]):
                failures.append(f"{identity}: expected {row['expected_errors']} diagnostics, got {error_count}")
        elif expected == "internal_error":
            diagnostic = ANSI.sub("", compiled.stdout + compiled.stderr).lower()
            if evidence.lower() not in diagnostic:
                failures.append(f"{identity}: missing known internal-error evidence {evidence!r}")
    if classification != "known_difference" and isinstance(case, regression.RunCase) and outcome == "accept" and ran is not None:
        failures.extend(regression.check_result(f"{identity} sawc", ran,
                                                case.stdout, case.exit_code))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--binary", type=Path, default=Path(".build/minivm/minivm"))
    parser.add_argument("--sawc", type=Path, default=REPO / "sawc" / "sawc.py")
    parser.add_argument("--sawc-python", default=sys.executable)
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--section")
    parser.add_argument("--filter")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--compile-timeout", type=int, default=regression.SAWC_COMPILE_TIMEOUT)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    rows, failures = load_manifest(args.manifest)
    if not failures:
        issues = {str(row["issue"]) for row in rows.values()
                  if row.get("classification") == "known_difference" and isinstance(row.get("issue"), str)}
        for issue in sorted(issues):
            failure = issue_failure(issue)
            if failure:
                failures.append(failure)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    if args.validate_only:
        print(f"differential manifest: {len(rows)} fixtures classified")
        return 0
    binary = args.binary.resolve()
    sawc = args.sawc.resolve()
    if not binary.is_file() or not sawc.is_file():
        parser.error("--binary and --sawc must name existing files")
    selected = []
    registry = identities()
    for identity, row in rows.items():
        case = registry[identity]
        if args.section and case.section != args.section:
            continue
        if args.filter and args.filter not in case.name:
            continue
        selected.append((identity, row, case))
    if not selected:
        parser.error("selection contains no fixtures")
    explicit_artifacts = args.artifacts is not None
    if explicit_artifacts:
        artifacts = args.artifacts.resolve()
        artifacts.mkdir(parents=True, exist_ok=True)
        temporary = None
    else:
        artifacts = Path(tempfile.mkdtemp(prefix="minivm-differential-", dir=REPO / ".build"))
        temporary = True
    counts = {kind: 0 for kind in KINDS}
    known_internal_errors = 0
    engine_counts = {"prototype_vm": 0, "prototype_emit": 0, "clang": 0,
                     "native": 0, "sawc_compile": 0, "sawc_run": 0}
    try:
        for identity, row, case in selected:
            classification = str(row["classification"])
            counts[classification] += 1
            if classification == "known_difference" and row.get("sawc") == "internal_error":
                known_internal_errors += 1
            if classification == "subset_exclusion":
                continue
            case_dir = artifacts / identity.replace(":", "-").replace("/", "-")
            case_dir.mkdir(parents=True, exist_ok=True)
            try:
                prototype_failures, prototype_engines = run_prototype(binary, args.clang, case, case_dir)
                for engine, count in prototype_engines.items():
                    engine_counts[engine] += count
                run_accepted = isinstance(case, regression.RunCase) or (
                    classification == "known_difference" and row.get("sawc") == "accept")
                outcome, compiled, ran, sawc_error = sawc_outcome(args.sawc_python, sawc, case,
                    case_dir / "sawc", args.compile_timeout, case_dir, run_accepted)
                engine_counts["sawc_compile"] += 1
                if ran is not None:
                    engine_counts["sawc_run"] += 1
            except subprocess.TimeoutExpired as error:
                failures.append(f"{identity}: timed out after {error.timeout}s")
                continue
            failures.extend(f"{identity}: {failure}" for failure in prototype_failures)
            if sawc_error or compiled is None:
                failures.append(f"{identity}: sawc {sawc_error or 'did not complete'}")
            else:
                failures.extend(check_sawc_expectation(identity, row, case, outcome, compiled, ran))
    finally:
        pass
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"differential: {len(failures)} failure(s); artifacts {artifacts}")
        return 1
    if temporary:
        shutil.rmtree(artifacts)
    executed = counts["agreement"] + counts["known_difference"]
    if executed == 0:
        print(f"differential: classifications validated; agreement=0 known=0 excluded={counts['subset_exclusion']}; no engines selected")
        return 0
    print(f"differential: PASS; agreement={counts['agreement']} known={counts['known_difference']} known_internal_errors={known_internal_errors} excluded={counts['subset_exclusion']}; engines=" +
          ",".join(f"{name}:{count}" for name, count in engine_counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
