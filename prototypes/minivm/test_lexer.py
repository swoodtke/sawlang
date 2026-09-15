#!/usr/bin/env python3
"""Whole-source lexer differential for the M16 mini-VM acceptance gate."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LEXER = REPO / "selfhost/lexer/src/lib.saw"
LEXER_TESTS = REPO / "selfhost/lexer/tests"


@dataclass(frozen=True)
class Case:
    name: str
    data: bytes


class EngineFailure(RuntimeError):
    def __init__(self, message: str, stdout: bytes = b"", stderr: bytes = b""):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def saw_string_chunks(data: bytes) -> list[str]:
    """Saw statements that reconstruct data exactly, including invalid UTF-8."""
    chunks: list[str] = []
    text: list[str] = []

    def flush() -> None:
        if text:
            chunks.append(f'try! b.append("{"".join(text)}")')
            text.clear()

    decoded = data.decode("utf-8", errors="surrogateescape")
    for char in decoded:
        code = ord(char)
        if 0xDC80 <= code <= 0xDCFF:
            flush()
            chunks.append(
                f"try! b.append(Byte(UInt8.from(truncating: {code - 0xDC00})))")
        elif char == "\\":
            text.append("\\\\")
        elif char == '"':
            text.append('\\"')
        elif char == "{":
            text.append("\\{")
        elif char == "}":
            text.append("\\}")
        elif char == "\n":
            text.append("\\n")
        elif char == "\r":
            text.append("\\r")
        elif char == "\t":
            text.append("\\t")
        elif code == 0:
            text.append("\\0")
        elif code < 32 or code == 127:
            flush()
            chunks.append(
                f"try! b.append(Byte(UInt8.from(truncating: {code})))")
        else:
            text.append(char)
        if sum(len(piece) for piece in text) >= 2048:
            flush()
    flush()
    return chunks


DRIVER = r'''
func dump_bytes(label: String, value: String) {
    print(label)
    print(value.len())
    var i = 0
    while i < value.len() {
        print(value.byte_at(i) as Int)
        i += 1
    }
}

func dump_case(case_id: Int, source: String) {
    print("CASE")
    print(case_id)
    match lex(source) {
        case Ok(result) -> {
            print("OK")
            print("TOKENS")
            print(result.tokens.len())
            var i = 0
            while i < result.tokens.len() {
                let token = result.tokens[i]
                print("TOKEN")
                dump_bytes("KIND", kind_name(token.kind))
                dump_bytes("VALUE", token.value)
                print("LINE")
                print(token.line)
                print("COL")
                print(token.col)
                if let suffix = token.suffix {
                    print("SUFFIX-SOME")
                    dump_bytes("SUFFIX", suffix)
                } else {
                    print("SUFFIX-NONE")
                }
                print("SEG-START")
                print(token.seg_start)
                print("SEG-COUNT")
                print(token.seg_count)
                i += 1
            }
            print("DOCS")
            print(result.docs.len())
            i = 0
            while i < result.docs.len() {
                let doc = result.docs[i]
                print("DOC")
                dump_bytes("DOC-KIND", doc.kind)
                dump_bytes("DOC-TEXT", doc.text)
                print("LINE")
                print(doc.line)
                print("COL")
                print(doc.col)
                i += 1
            }
            print("SEGMENTS")
            print(result.segments.len())
            i = 0
            while i < result.segments.len() {
                let segment = result.segments[i]
                match segment.kind {
                    case Text -> { print("SEGMENT-TEXT") },
                    case Expr -> { print("SEGMENT-EXPR") }
                }
                dump_bytes("SEGMENT-VALUE", segment.text)
                print("LINE")
                print(segment.line)
                print("COL")
                print(segment.col)
                i += 1
            }
        },
        case Err(error) -> {
            print("ERROR")
            print("LINE")
            print(error.line)
            print("COL")
            print(error.col)
            dump_bytes("MESSAGE", error.message)
        }
    }
    print("END-CASE")
}
'''


def generated_source(lexer: bytes, cases: list[Case]) -> bytes:
    lines = [lexer.decode("utf-8"), "\n", DRIVER, "\nfunc main() {\n"]
    for index, case in enumerate(cases):
        lines.append("    if true {\n        var b = StringBuilder()\n")
        for statement in saw_string_chunks(case.data):
            lines.append(f"        {statement}\n")
        lines.append(f"        dump_case({index}, b.build())\n    }}\n")
    lines.append("}\n")
    return "".join(lines).encode("utf-8")


def run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, check=False, cwd=REPO)


def engine_output(label: str, argv: list[str], timeout: float) -> bytes:
    try:
        result = run(argv, timeout)
    except subprocess.TimeoutExpired as error:
        raise EngineFailure(f"{label} timed out after {error.timeout}s",
                            error.stdout or b"", error.stderr or b"") from error
    if result.returncode != 0:
        raise EngineFailure(
            f"{label} exited {result.returncode}\nstdout={result.stdout[:2000]!r}\n"
            f"stderr={result.stderr[:4000]!r}", result.stdout, result.stderr)
    if result.stderr:
        raise EngineFailure(f"{label} wrote stderr: {result.stderr[:4000]!r}",
                            result.stdout, result.stderr)
    return result.stdout


def default_cases() -> list[Case]:
    goldens = [
        Case("golden-empty", b""),
        Case("golden-simple", b"let x = 1\n"),
        Case("golden-error", b'"unterminated'),
        Case("golden-doc", b"/// hello\nlet x = 1\n"),
        Case("golden-interpolation", b'"left {x} right"\n'),
    ]
    corpus = [Case(f"lexer-test/{path.name}", path.read_bytes())
              for path in sorted(LEXER_TESTS.glob("*.saw"))]
    corpus.extend([
        Case("tracked/factorial", (HERE / "examples/factorial.saw").read_bytes()),
        Case("tracked/lexer", LEXER.read_bytes()),
        Case("edges/nul-error", b"a\x00b"),
        Case("edges/whitespace-controls", b"a\t b\r\n"),
        Case("edges/numbers", b"0 1_000 0xff 0b1010 0o77 127i8 255u8 32767i16 65535u16 2147483647i32 4294967295u32 9223372036854775807i64 18446744073709551615u64 1.0 1e9 1.25e-3 1..2 1..=2 1...2\n"),
        Case("edges/number-error-u8", b"256u8"),
        Case("edges/number-error-i8", b"128i8"),
        Case("edges/number-error-u64", b"18446744073709551616u64"),
        Case("edges/number-error-unsuffixed", b"9223372036854775808"),
        Case("edges/number-error-hex", b"0x1_0000_0000_0000_0000"),
        Case("edges/valid-unicode-escapes", b'"\\u{0} \\u{7f} \\u{80} \\u{10ffff}"\n'),
        Case("edges/unicode-surrogate", b'"\\u{d800}"'),
        Case("edges/unicode-out-of-range", b'"\\u{110000}"'),
        Case("edges/raw-unicode", "é λ 🙂\n".encode()),
        Case("edges/comments-docs", b"//! module\n/// item\nlet x = 1 // tail\n//// ordinary\n"),
        Case("edges/unknown-string-escape", b'"\\q"'),
        Case("edges/unclosed-interpolation", b'"a {x"'),
        Case("edges/invalid-utf8", b"let \xff = 1\n"),
        Case("edges/keywords", b"func let var if else guard return true false struct extension self init None enum case match while break continue trait for in extern not move unsafe borrows lend as try catch static public\n"),
        Case("edges/operators", b"+ - * / % == != < > <= >= && || & | ^ ~ &+ &- &* ! = += -= *= /= %= &= |= ^= <<= >>= ? ?? ?. .. ..= ... ( ) { } [ ] , : ; -> . @\n"),
        Case("edges/hash-directives", b"#file #line #function #lend_var\n"),
        Case("edges/dollar-parameters", b"$0 $1 $999\n"),
        Case("edges/hash-error-empty", b"#"),
        Case("edges/hash-error-unknown", b"#unknown"),
        Case("edges/dollar-error", b"$x"),
    ])
    return goldens + corpus


def large_cases(limit: int) -> list[Case]:
    if limit == 0:
        return []
    chosen: list[Case] = []
    excluded = {LEXER.resolve(), (HERE / "examples/factorial.saw").resolve()}
    excluded.update(path.resolve() for path in LEXER_TESTS.glob("*.saw"))
    listed = run(["git", "ls-files", "-z", "--", "*.saw"], 30.0)
    if listed.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {listed.stderr!r}")
    for relative in sorted(filter(None, listed.stdout.split(b"\0"))):
        path = REPO / relative.decode("utf-8")
        if path.resolve() in excluded:
            continue
        name = f"large/{path.relative_to(REPO)}"
        chosen.append(Case(name, path.read_bytes()))
        if len(chosen) >= limit:
            break
    return chosen


def split_case_output(output: bytes) -> list[bytes]:
    marker = b"CASE\n"
    if output and not output.startswith(marker):
        raise RuntimeError(f"canonical output lacks initial CASE marker: {output[:80]!r}")
    records: list[bytearray] = []
    for line in output.splitlines(keepends=True):
        if line == marker:
            records.append(bytearray())
        records[-1].extend(line)
    return [bytes(record) for record in records]


def bytes_field(label: str, value: bytes) -> bytes:
    return (label.encode() + b"\n" + str(len(value)).encode() + b"\n" +
            b"".join(str(byte).encode() + b"\n" for byte in value))


def token(kind: bytes, value: bytes, line: int, col: int,
          seg_start: int = 0, seg_count: int = 0) -> bytes:
    return (b"TOKEN\n" + bytes_field("KIND", kind) + bytes_field("VALUE", value) +
            f"LINE\n{line}\nCOL\n{col}\nSUFFIX-NONE\n"
            f"SEG-START\n{seg_start}\nSEG-COUNT\n{seg_count}\n".encode())


def golden_records(case_id: int) -> dict[str, bytes]:
    prefix = f"CASE\n{case_id}\n".encode()
    eof_1 = token(b"EOF", b"", 1, 1)
    empty = prefix + b"OK\nTOKENS\n1\n" + eof_1 + b"DOCS\n0\nSEGMENTS\n0\nEND-CASE\n"
    simple_tokens = (token(b"LET", b"let", 1, 1) + token(b"IDENT", b"x", 1, 5) +
                     token(b"ASSIGN", b"=", 1, 7) + token(b"INT", b"1", 1, 9) +
                     token(b"NEWLINE", b"\n", 1, 10) +
                     token(b"EOF", b"", 2, 1))
    simple = prefix + b"OK\nTOKENS\n6\n" + simple_tokens + b"DOCS\n0\nSEGMENTS\n0\nEND-CASE\n"
    error = (prefix + b"ERROR\nLINE\n1\nCOL\n14\n" +
             bytes_field("MESSAGE", b"Unterminated string") + b"END-CASE\n")
    # Comment trivia leaves its terminating newline in the token stream.
    doc = (prefix + b"OK\nTOKENS\n7\n" + token(b"NEWLINE", b"\n", 1, 10) +
           token(b"LET", b"let", 2, 1) + token(b"IDENT", b"x", 2, 5) +
           token(b"ASSIGN", b"=", 2, 7) + token(b"INT", b"1", 2, 9) +
           token(b"NEWLINE", b"\n", 2, 10) +
           token(b"EOF", b"", 3, 1) + b"DOCS\n1\nDOC\n" +
           bytes_field("DOC-KIND", b"doc") + bytes_field("DOC-TEXT", b"hello") +
           b"LINE\n1\nCOL\n1\nSEGMENTS\n0\nEND-CASE\n")
    interpolation = (prefix + b"OK\nTOKENS\n3\n" +
                     token(b"INTERP_STRING", b"left {x} right", 1, 1, 0, 3) +
                     token(b"NEWLINE", b"\n", 1, 17) +
                     token(b"EOF", b"", 2, 1) + b"DOCS\n0\nSEGMENTS\n3\n" +
                     b"SEGMENT-TEXT\n" + bytes_field("SEGMENT-VALUE", b"left ") +
                     b"LINE\n0\nCOL\n0\nSEGMENT-EXPR\n" +
                     bytes_field("SEGMENT-VALUE", b"x") + b"LINE\n1\nCOL\n7\n" +
                     b"SEGMENT-TEXT\n" + bytes_field("SEGMENT-VALUE", b" right") +
                     b"LINE\n0\nCOL\n0\nEND-CASE\n")
    return {"golden-empty": empty, "golden-simple": simple,
            "golden-error": error, "golden-doc": doc,
            "golden-interpolation": interpolation}


def validate_records(output: bytes, count: int) -> list[str]:
    records = split_case_output(output)
    failures = []
    if len(records) != count:
        failures.append(f"expected {count} records, got {len(records)}")
    for index, record in enumerate(records):
        lines = record.splitlines()
        if len(lines) < 3 or lines[0] != b"CASE" or lines[1] != str(index).encode():
            failures.append(f"record {index} has invalid case id/header")
        if not record.endswith(b"END-CASE\n"):
            failures.append(f"record {index} lacks END-CASE")
    return failures


def check_independent_goldens(cases: list[Case], output: bytes) -> list[str]:
    """Compare complete records authored independently of the Saw serializer."""
    failures: list[str] = []
    records = split_case_output(output)
    for index, case in enumerate(cases):
        if not case.name.startswith("golden-"):
            continue
        record = records[index] if index < len(records) else b""
        expected = golden_records(index)[case.name]
        if record != expected:
            failures.append(f"{case.name}: complete record differs from independent golden; "
                            f"{difference(record, expected)}")
    return failures


def difference(left: bytes, right: bytes, context: int = 120) -> str:
    offset = next((i for i, pair in enumerate(zip(left, right)) if pair[0] != pair[1]),
                  min(len(left), len(right)))
    start, end = max(0, offset - context), offset + context
    return (f"first difference at byte {offset}; "
            f"VM[{start}:{end}]={left[start:end]!r}; "
            f"other[{start}:{end}]={right[start:end]!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=REPO / ".build/minivm/minivm")
    parser.add_argument("--sawc", type=Path, default=REPO / "sawc/sawc.py")
    parser.add_argument("--sawc-python", default=sys.executable)
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--vm-budget", type=int, default=50_000_000)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--compile-timeout", type=float, default=240.0)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--case-prefix", action="append", default=[],
                        help="run only case names beginning with this prefix (repeatable)")
    parser.add_argument("--large", action="store_true")
    parser.add_argument("--large-limit", type=int, default=100)
    parser.add_argument("--no-asan", action="store_true")
    args = parser.parse_args()
    if (args.batch_size <= 0 or args.vm_budget <= 0 or args.timeout <= 0 or
            args.compile_timeout <= 0 or args.large_limit < 0):
        parser.error("batch size, VM budget, and timeouts must be positive; "
                     "large limit cannot be negative")
    binary, sawc = args.binary.resolve(), args.sawc.resolve()
    if not binary.is_file() or not sawc.is_file():
        parser.error("--binary and --sawc must name existing files")

    cases = default_cases() + (large_cases(args.large_limit) if args.large else [])
    if args.case_prefix:
        cases = [case for case in cases
                 if any(case.name.startswith(prefix) for prefix in args.case_prefix)]
        if not cases:
            parser.error("--case-prefix selected no cases")
    lexer = LEXER.read_bytes()
    failures: list[str] = []
    artifact_root = REPO / ".build/scratch"
    artifact_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="minivm-lexer-") as raw_temp:
        temp = Path(raw_temp)
        for batch_no, start in enumerate(range(0, len(cases), args.batch_size)):
            batch = cases[start:start + args.batch_size]
            source = temp / f"lexer-batch-{batch_no}.saw"
            source.write_bytes(generated_source(lexer, batch))
            label = f"batch {batch_no} ({', '.join(case.name for case in batch)})"
            failures_before = len(failures)
            print(f"RUN: {label}", flush=True)
            try:
                vm = engine_output(
                    f"{label} VM",
                    [str(binary), "run", str(source), "--budget", str(args.vm_budget)],
                    args.timeout)
                emitted = engine_output(
                    f"{label} emit", [str(binary), "emit-llvm", str(source)],
                    args.compile_timeout)
                ll_path = temp / f"lexer-batch-{batch_no}.ll"
                ll_path.write_bytes(emitted)
                outputs = {"VM": vm}
                modes = [("O0", ["-O0"]), ("O2", ["-O2"])]
                if not args.no_asan:
                    modes.append(("ASan", ["-O1", "-fsanitize=address"]))
                for mode, flags in modes:
                    native = temp / f"lexer-batch-{batch_no}-{mode}"
                    compiled = run([args.clang, *flags, str(ll_path), "-o", str(native)],
                                   args.compile_timeout)
                    if compiled.returncode != 0:
                        raise RuntimeError(f"{label} clang {mode}: {compiled.stderr[:4000]!r}")
                    outputs[mode] = engine_output(f"{label} native {mode}",
                                                  [str(native)], args.timeout)
                sawc_bin = temp / f"lexer-batch-{batch_no}-sawc"
                compiled = run([args.sawc_python, str(sawc), str(source),
                                "-o", str(sawc_bin)], args.compile_timeout)
                if compiled.returncode != 0:
                    raise RuntimeError(
                        f"{label} sawc compile exited {compiled.returncode}: "
                        f"{compiled.stdout[:2000]!r} {compiled.stderr[:4000]!r}")
                outputs["sawc"] = engine_output(f"{label} sawc", [str(sawc_bin)],
                                                args.timeout)
                for engine, output in outputs.items():
                    failures.extend(f"{label} {engine}: {failure}"
                                    for failure in validate_records(output, len(batch)))
                    if output != vm:
                        artifact = Path(tempfile.mkdtemp(
                            prefix=f"lexer-diff-{batch_no}-",
                            dir=artifact_root))
                        (artifact / "source.saw").write_bytes(source.read_bytes())
                        (artifact / "vm.out").write_bytes(vm)
                        (artifact / f"{engine}.out").write_bytes(output)
                        failures.append(f"{label}: {engine} differs from VM; "
                                        f"{difference(vm, output)}; artifacts: {artifact}")
                failures.extend(check_independent_goldens(batch, vm))
                if len(failures) == failures_before:
                    print(f"PASS: {label} [{', '.join(outputs)}]", flush=True)
                else:
                    artifact = Path(tempfile.mkdtemp(prefix=f"lexer-records-{batch_no}-",
                                                    dir=artifact_root))
                    (artifact / "source.saw").write_bytes(source.read_bytes())
                    for engine, output in outputs.items():
                        (artifact / f"{engine}.out").write_bytes(output)
                    print(f"FAIL: {label}; artifacts: {artifact}", flush=True)
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                artifact = Path(tempfile.mkdtemp(
                    prefix=f"lexer-failure-{batch_no}-", dir=artifact_root))
                (artifact / "source.saw").write_bytes(source.read_bytes())
                (artifact / "error.txt").write_text(str(error)[:8000])
                if isinstance(error, EngineFailure):
                    (artifact / "stdout").write_bytes(error.stdout)
                    (artifact / "stderr").write_bytes(error.stderr)
                failures.append(f"{label}: {str(error)[:4000]}; artifacts: {artifact}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    mode = "large" if args.large else "default"
    print(f"lexer differential: {len(cases)} inputs passed ({mode}, "
          f"batch size {args.batch_size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
