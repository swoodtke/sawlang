#!/usr/bin/env python3
"""Focused M18 arena-AST contract and cross-engine harness."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LEXER = REPO / "selfhost/lexer/src/lib.saw"
PARSER = HERE / "src/lib.saw"
DRIVER = HERE / "driver.saw"
FIXTURES = HERE / "fixtures/cases.json"


@dataclass(frozen=True)
class Case:
    name: str
    source: bytes
    tree: dict[str, object] | None = None
    error: tuple[int, int, str] | None = None


@dataclass(frozen=True)
class Node:
    kind: str
    text: str
    first_child: int
    child_count: int
    start_token: int
    end_token: int
    line: int
    col: int


@dataclass(frozen=True)
class Tree:
    root: int
    nodes: list[Node]
    children: list[int]


@dataclass(frozen=True)
class ParsedCase:
    case_id: int
    token_count: int
    tree: Tree | None
    error: tuple[int, int, str] | None


class EngineFailure(RuntimeError):
    def __init__(self, label: str, argv: list[str], message: str,
                 stdout: bytes = b"", stderr: bytes = b""):
        super().__init__(f"{label}: {message}")
        self.argv = argv
        self.stdout = stdout
        self.stderr = stderr


class Cursor:
    def __init__(self, lines: list[bytes]):
        self.lines = lines
        self.position = 0

    def take(self, expected: str | None = None) -> bytes:
        if self.position >= len(self.lines):
            raise ValueError(f"unexpected end of record, expected {expected or 'value'}")
        value = self.lines[self.position]
        self.position += 1
        if expected is not None and value != expected.encode():
            raise ValueError(f"expected {expected!r}, got {value!r}")
        return value

    def integer(self, label: str) -> int:
        self.take(label)
        try:
            return int(self.take())
        except ValueError as error:
            raise ValueError(f"{label} is not an integer") from error

    def bytes_field(self, label: str) -> str:
        self.take(label)
        length = int(self.take())
        if length < 0:
            raise ValueError(f"{label} has negative byte length")
        data = bytes(int(self.take()) for _ in range(length))
        return data.decode("utf-8")


def fixture_cases() -> list[Case]:
    raw = json.loads(FIXTURES.read_text(encoding="utf-8"))
    if type(raw) is not dict or raw.get("version") != 1 or type(raw.get("cases")) is not list:
        raise ValueError("fixture manifest requires version 1 and a cases array")
    result: list[Case] = []
    names: set[str] = set()
    for row in raw["cases"]:
        if type(row) is not dict or type(row.get("name")) is not str or row["name"] in names:
            raise ValueError("fixture names must be unique strings")
        if type(row.get("source")) is not str or type(row.get("tree")) is not dict:
            raise ValueError(f"{row['name']}: source and independently authored tree required")
        names.add(row["name"])
        result.append(Case(row["name"], row["source"].encode(), tree=row["tree"]))
    return result


def generated_cases() -> list[Case]:
    def node(kind: str, text: str = "", children: list[dict[str, object]] | None = None,
             **fields: int) -> dict[str, object]:
        result: dict[str, object] = {"kind": kind, "text": text, "children": children or []}
        result.update(fields)
        return result

    def program(block_children: list[dict[str, object]], return_type: str = "Int") -> dict[str, object]:
        return node("Program", children=[node("Function", "f", [
            node("NamedType", return_type), node("Block", children=block_children)])])

    growth_lines = "".join(f" let value{i} = {i}\n" for i in range(96))
    errors = [
        Case("error-lex-unterminated-string", b'"unterminated', error=(1, 14, "Unterminated string")),
        Case("error-item-doc-comment", b"/// item\nfunc f() {}\n",
             error=(1, 1, "documentation comments are not supported")),
        Case("error-module-doc-comment", b"//! module\nfunc f() {}\n",
             error=(1, 1, "documentation comments are not supported")),
        Case("error-interpolation", b'func f() { "a {x}" }', error=(1, 12, "interpolation")),
        Case("error-float", b"func f() { 1.5 }", error=(1, 12, "float")),
        Case("error-labelled-call", b"func f() { g(value: 1) }", error=(1, 19, "label")),
        Case("error-member", b"func f() { value.field }", error=(1, 17, "member")),
        Case("error-index", b"func f() { value[0] }", error=(1, 17, "index")),
        Case("error-assignment-in-binding", b"func f() { let x = value = 1 }", error=(1, 26, "assignment")),
        Case("error-semicolon", b"func f() { value; }", error=(1, 17, "semicolon")),
        Case("error-control", b"func f() { if true { 1 } else { 2 } }", error=(1, 12, "control")),
        Case("error-declaration", b"struct Nope {}", error=(1, 1, "function")),
        Case("error-unclosed-call", b"func f() { g(1 }", error=(1, 16, "closing parenthesis")),
        Case("error-trailing", b"func f() {} garbage", error=(1, 13, "function")),
        Case("error-generic-type", b"func f(x: Box<Int>) {}", error=(1, 14, "")),
        Case("error-reference-type", b"func f(x: &Int) {}", error=(1, 11, "")),
        Case("error-optional-type", b"func f(x: Int?) {}", error=(1, 14, "")),
        Case("error-external-parameter-label", b"func f(label x: Int) {}", error=(1, 14, "")),
        Case("error-default-parameter", b"func f(x: Int = 1) {}", error=(1, 15, "")),
        Case("error-newline-after-equals", b"func f() { let x =\n1 }", error=(1, 19, "expression")),
        Case("error-newline-after-unary", b"func f() { -\n1 }", error=(1, 13, "expression")),
        Case("error-newline-after-unary-after-binary", b"func f() { 1 + -\n2 }", error=(1, 17, "expression")),
        Case("error-missing-rhs", b"func f() { 1 + }", error=(1, 16, "expression")),
        Case("error-empty-group", b"func f() { () }", error=(1, 13, "expression")),
        Case("error-extra-comma", b"func f() { g(1,,2) }", error=(1, 16, "expression")),
        Case("error-adjacent-operands", b"func f() { 1 2 }", error=(1, 14, "newline")),
    ]
    syntax_controls = [
        Case("newline-and-trailing-comma", b"func f(\n x\n:\nInt\n,\n) -> Int\n{ g(\n x,\n) }\n",
             tree=node("Program", children=[node("Function", "f", [
                 node("Parameter", "x", [node("NamedType", "Int")]),
                 node("NamedType", "Int"),
                 node("Block", children=[node("FinalExpression", children=[
                     node("Call", children=[node("Identifier", "g"), node("Identifier", "x")])])])])])),
        Case("return-newline", b"func f() -> Int {\n return\n 1\n}\n",
             tree=program([node("Return"), node("FinalExpression", children=[node("IntegerLiteral", "1")])])),
        Case("newline-after-binary", b"func f() -> Int { 1 +\n 2 }\n",
             tree=program([node("FinalExpression", children=[node("Binary", "+", [
                 node("IntegerLiteral", "1"), node("IntegerLiteral", "2")])])])),
        Case("newline-after-binary-before-unary", b"func f() -> Int { 1 +\n -2 }\n",
             tree=program([node("FinalExpression", children=[node("Binary", "+", [
                 node("IntegerLiteral", "1"), node("Unary", "-", [node("IntegerLiteral", "2")])])])])),
        Case("parenthesized-newline-after-unary", b"func f() -> Int { (1 + -\n2) }\n",
             tree=program([node("FinalExpression", children=[node("Binary", "+", [
                 node("IntegerLiteral", "1"), node("Unary", "-", [node("IntegerLiteral", "2")])])])])),
        Case("grouped-callee", b"func f() -> Int { (callable)(1) }\n",
             tree=program([node("FinalExpression", children=[node("Call", children=[
                 node("Identifier", "callable", start_token=8, end_token=9),
                 node("IntegerLiteral", "1")], start_token=7, end_token=13)])])),
        Case("call-result-callee", b"func f() -> Int { factory()(1) }\n",
             tree=program([node("FinalExpression", children=[node("Call", children=[
                 node("Call", children=[node("Identifier", "factory")], start_token=7, end_token=10),
                 node("IntegerLiteral", "1")], start_token=7, end_token=13)])])),
        Case("leading-minus-new-expression", b"func f() -> Int {\n 1\n -2\n}\n",
             tree=program([node("ExpressionStatement", children=[node("IntegerLiteral", "1")]),
                           node("FinalExpression", children=[node("Unary", "-", [node("IntegerLiteral", "2")])])])),
        Case("many-shallow-unaries", ("func f() -> Int { " + " + ".join("-1" for _ in range(300)) + " }\n").encode()),
    ]
    return [Case("arena-growth", f"func growth() -> Int {{\n{growth_lines} 95\n}}\n".encode())] + syntax_controls + errors + assignment_cases()


def assignment_cases() -> list[Case]:
    def node(kind, text="", children=None, **anchors):
        return {"kind": kind, "text": text, "children": children or [], **anchors}

    def program(statements):
        return node("Program", children=[node("Function", "f", [
            node("NamedType", "Void"), node("Block", children=statements)])])

    cases = []
    operator_names = {"=": "plain", "+=": "plus", "-=": "minus", "*=": "star",
                      "/=": "slash", "%=": "percent"}
    for op in operator_names:
        kind = "Assign" if op == "=" else "CompoundAssign"
        cases.append(Case("assignment-" + operator_names[op],
                          f"func f() {{ (x) {op} g(1 + 2) }}\n".encode(),
                          tree=program([node(kind, "" if op == "=" else op[0], [
                              node("Identifier", "x", start_token=6, end_token=7, line=1, col=13),
                              node("Call", children=[node("Identifier", "g"),
                                   node("Binary", "+", [node("IntegerLiteral", "1"),
                                                        node("IntegerLiteral", "2")])])],
                              start_token=5, end_token=15, line=1, col=13)])))
    cases.append(Case("assignment-before-tail",
                      b"func f() { var x = 1\n x = 2\n x += 3\n x }\n",
                      tree=program([
                          node("Var", "x", [node("IntegerLiteral", "1")]),
                          node("Assign", children=[node("Identifier", "x"), node("IntegerLiteral", "2")]),
                          node("CompoundAssign", "+", [node("Identifier", "x"), node("IntegerLiteral", "3")]),
                          node("FinalExpression", children=[node("Identifier", "x")])])) )
    # Locate each error at the source token that first makes this subset invalid.
    for name, source, marker, message in [
        ("chain", "func f() { x = y = 2 }", "= 2", "assignment"),
        ("compound-chain", "func f() { x += y = 2 }", "= 2", "assignment"),
        ("group", "func f() { (x = 1) }", "= 1", "assignment"),
        ("argument", "func f() { g(x = 1) }", "= 1", "assignment"),
        ("return", "func f() { return x = 1 }", "= 1", "assignment"),
        ("literal-target", "func f() { 1 = 2 }", "= 2", "target"),
        ("binary-target", "func f() { x + y = 2 }", "= 2", "target"),
        ("call-target", "func f() { g() += 2 }", "+= 2", "target"),
        ("missing-value", "func f() { x = }", "}", "expression"),
        ("missing-target", "func f() { = 1 }", "= 1", "assignment"),
        ("member", "func f() { x.a = 1 }", ".a", "member"),
        ("index", "func f() { x[0] = 1 }", "[0]", "index"),
        ("boundary", "func f() { x = 1 y = 2 }", "y =", "boundary"),
    ]:
        cases.append(Case("error-assignment-" + name, source.encode(),
                          error=(1, source.index(marker) + 1, message)))
    for op, name in (("&=", "and"), ("|=", "or"), ("^=", "xor"),
                     ("<<=", "shift-left"), (">>=", "shift-right")):
        cases.append(Case("error-assignment-bitwise-" + name,
                          f"func f() {{ x {op} 1 }}".encode(), error=(1, 14, "bitwise")))
    for op, name in operator_names.items():
        source = f"func f() {{ x {op}\n1 }}"
        cases.append(Case("error-assignment-newline-" + name, source.encode(),
                          error=(1, source.index("\n") + 1, "expression")))
    for depth in (256, 257):
        prefix = "func f() { x = "
        source = prefix + "(" * depth + "1" + ")" * depth + " }"
        expected = program([node("Assign", children=[node("Identifier", "x"), node("IntegerLiteral", "1")])])
        cases.append(Case(f"assignment-depth-{depth}", source.encode(),
                          tree=expected if depth == 256 else None,
                          error=(1, len(prefix) + 257, "nesting") if depth == 257 else None))
        target_prefix = "func f() { "
        target = "(" * depth + "x" + ")" * depth
        target_source = target_prefix + target + " = 1 }"
        target_tree = program([node("Assign", children=[
            node("Identifier", "x", start_token=5 + depth, end_token=6 + depth,
                 line=1, col=len(target_prefix) + depth + 1),
            node("IntegerLiteral", "1")], start_token=5,
            end_token=8 + 2 * depth, line=1, col=len(target_prefix) + depth + 1)])
        cases.append(Case(f"assignment-target-depth-{depth}", target_source.encode(),
                          tree=target_tree if depth == 256 else None,
                          error=(1, len(target_prefix) + 257, "nesting") if depth == 257 else None))
    long_rhs = " + ".join("1" for _ in range(300))
    cases.append(Case("assignment-long-shallow-rhs",
                      f"func f() {{ x = {long_rhs} }}\n".encode()))
    return cases


def depth_cases() -> list[Case]:
    def nested(depth: int) -> bytes:
        return ("func depth() -> Int { " + "(" * depth + "1" + ")" * depth + " }\n").encode()
    def unary(depth: int) -> bytes:
        return ("func depth() -> Int { " + "-" * depth + "1 }\n").encode()
    def calls(depth: int) -> bytes:
        return ("func depth() -> Int { " + "f(" * depth + "1" + ")" * depth + " }\n").encode()
    def mixed(depth: int) -> bytes:
        # Alternating unary and grouping consumes one shared nesting budget per prefix.
        prefixes = "".join("-" if i % 2 == 0 else "(" for i in range(depth))
        closes = ")" * (depth // 2)
        return ("func depth() -> Int { " + prefixes + "1" + closes + " }\n").encode()
    def leaf() -> dict[str, object]:
        return {"kind": "IntegerLiteral", "text": "1", "children": []}
    def wrap(expression: dict[str, object]) -> dict[str, object]:
        return {"kind": "Program", "text": "", "children": [
            {"kind": "Function", "text": "depth", "children": [
                {"kind": "NamedType", "text": "Int", "children": []},
                {"kind": "Block", "text": "", "children": [
                    {"kind": "FinalExpression", "text": "", "children": [expression]}
                ]}
            ]}
        ]}
    unary_tree = leaf()
    call_tree = leaf()
    for _ in range(256):
        unary_tree = {"kind": "Unary", "text": "-", "children": [unary_tree]}
        call_tree = {"kind": "Call", "text": "", "children": [
            {"kind": "Identifier", "text": "f", "children": []}, call_tree]}
    return [Case("depth-groups-256", nested(256), tree=wrap(leaf())),
            Case("depth-groups-257", nested(257), error=(1, 279, "expression nesting exceeds 256")),
            Case("depth-unary-256", unary(256), tree=wrap(unary_tree)),
            Case("depth-unary-257", unary(257), error=(1, 279, "expression nesting exceeds 256")),
            Case("depth-calls-256", calls(256), tree=wrap(call_tree)),
            Case("depth-calls-257", calls(257), error=(1, 536, "expression nesting exceeds 256")),
            Case("depth-mixed-256", mixed(256)),
            Case("depth-mixed-257", mixed(257), error=(1, 279, "expression nesting exceeds 256"))]


def saw_string_chunks(data: bytes) -> list[str]:
    chunks: list[str] = []
    text: list[str] = []

    def flush() -> None:
        if text:
            chunks.append(f'try! b.append("{"".join(text)}")')
            text.clear()

    for char in data.decode("utf-8", errors="surrogateescape"):
        code = ord(char)
        if 0xDC80 <= code <= 0xDCFF:
            flush()
            chunks.append(f"try! b.append(Byte(UInt8.from(truncating: {code - 0xDC00})))")
        elif char == "\\": text.append("\\\\")
        elif char == '"': text.append('\\"')
        elif char == "{": text.append("\\{")
        elif char == "}": text.append("\\}")
        elif char == "\n": text.append("\\n")
        elif char == "\r": text.append("\\r")
        elif char == "\t": text.append("\\t")
        elif code == 0: text.append("\\0")
        elif code < 32 or code == 127:
            flush()
            chunks.append(f"try! b.append(Byte(UInt8.from(truncating: {code})))")
        else: text.append(char)
        if len(text) >= 2048:
            flush()
    flush()
    return chunks


def assembled_source(cases: list[Case], parser_source: Path = PARSER) -> bytes:
    parts = [LEXER.read_text(encoding="utf-8"), "\n", parser_source.read_text(encoding="utf-8"),
             "\n", DRIVER.read_text(encoding="utf-8"), "\nfunc main() {\n"]
    for case_id, case in enumerate(cases):
        parts.append("    if true {\n        var b = StringBuilder()\n")
        for statement in saw_string_chunks(case.source):
            parts.append(f"        {statement}\n")
        parts.append(f"        dump_ast_case({case_id}, b.build())\n    }}\n")
    parts.append("}\n")
    return "".join(parts).encode()


def parse_record(record: bytes) -> ParsedCase:
    cursor = Cursor(record.splitlines())
    case_id = cursor.integer("CASE")
    token_count = cursor.integer("TOKEN-COUNT")
    outcome = cursor.take().decode()
    if outcome == "ERROR":
        error = (cursor.integer("LINE"), cursor.integer("COL"), cursor.bytes_field("MESSAGE"))
        cursor.take("END-CASE")
        if cursor.position != len(cursor.lines):
            raise ValueError("trailing error-record fields")
        return ParsedCase(case_id, token_count, None, error)
    if outcome != "OK":
        raise ValueError(f"unknown outcome {outcome!r}")
    root = cursor.integer("ROOT")
    node_count = cursor.integer("NODES")
    nodes: list[Node] = []
    for index in range(node_count):
        cursor.take("NODE")
        actual_index = cursor.integer("INDEX")
        if actual_index != index:
            raise ValueError(f"node index {actual_index}, expected {index}")
        cursor.take("KIND")
        kind = cursor.take().decode()
        text = cursor.bytes_field("TEXT")
        nodes.append(Node(kind, text, cursor.integer("FIRST-CHILD"),
                          cursor.integer("CHILD-COUNT"), cursor.integer("START-TOKEN"),
                          cursor.integer("END-TOKEN"), cursor.integer("LINE"),
                          cursor.integer("COL")))
    child_count = cursor.integer("CHILDREN")
    children = [cursor.integer("CHILD") for _ in range(child_count)]
    cursor.take("END-CASE")
    if cursor.position != len(cursor.lines):
        raise ValueError("trailing success-record fields")
    return ParsedCase(case_id, token_count, Tree(root, nodes, children), None)


def parse_output(output: bytes) -> list[ParsedCase]:
    marker = b"CASE\n"
    if output and not output.startswith(marker):
        raise ValueError("output lacks initial CASE marker")
    records: list[bytes] = []
    current = bytearray()
    for line in output.splitlines(keepends=True):
        if line == marker:
            if current:
                records.append(bytes(current))
                current.clear()
        current.extend(line)
    if current:
        records.append(bytes(current))
    return [parse_record(record) for record in records]


def validate_tree(tree: Tree, source: bytes | None = None,
                  token_count: int | None = None) -> list[str]:
    failures: list[str] = []
    if not (0 <= tree.root < len(tree.nodes)):
        return [f"root {tree.root} outside {len(tree.nodes)} nodes"]
    if tree.nodes[tree.root].kind != "Program":
        failures.append("root is not Program")
    elif token_count is not None and (tree.nodes[tree.root].start_token != 0 or
                                      tree.nodes[tree.root].end_token != token_count - 1):
        failures.append("Program span must cover exactly [0, EOF)")
    referenced: set[int] = set()
    owned_child_slots: set[int] = set()
    source_lines = source.decode("utf-8", errors="replace").splitlines() if source is not None else []
    empty_text_kinds = {"Program", "Block", "Return", "ExpressionStatement", "FinalExpression", "Call", "Assign"}
    named_kinds = {"Function", "Parameter", "NamedType", "Let", "Var", "Identifier",
                   "IntegerLiteral", "BooleanLiteral"}
    fixed_arity = {"Program": None, "Function": None, "Parameter": 1, "NamedType": 0,
                   "Block": None, "Let": None, "Var": None, "Return": None,
                   "ExpressionStatement": 1, "FinalExpression": 1, "Identifier": 0,
                   "IntegerLiteral": 0, "StringLiteral": 0, "BooleanLiteral": 0,
                   "Unary": 1, "Binary": 2, "Call": None, "Assign": 2, "CompoundAssign": 2}
    expected_first_child = 0
    for node_id, node in enumerate(tree.nodes):
        if node.first_child != expected_first_child:
            failures.append(f"node {node_id} first_child {node.first_child}, expected append offset {expected_first_child}")
        expected_first_child += node.child_count
        if node.first_child < 0 or node.child_count < 0 or node.first_child + node.child_count > len(tree.children):
            failures.append(f"node {node_id} child run is outside children arena")
            continue
        if node.kind not in fixed_arity:
            failures.append(f"node {node_id} has unknown kind {node.kind!r}")
        elif fixed_arity[node.kind] is not None and node.child_count != fixed_arity[node.kind]:
            failures.append(f"node {node_id} {node.kind} has arity {node.child_count}")
        if node.kind in empty_text_kinds and node.text:
            failures.append(f"node {node_id} {node.kind} must have empty text")
        if node.kind in named_kinds and not node.text:
            failures.append(f"node {node_id} {node.kind} must have nonempty text")
        if node.kind == "Unary" and node.text not in ("-", "not"):
            failures.append(f"node {node_id} has invalid unary operator {node.text!r}")
        if node.kind == "Binary" and node.text not in (
                "+", "-", "*", "/", "%", "<", "<=", ">", ">=", "==", "!=", "&&", "||"):
            failures.append(f"node {node_id} has invalid binary operator {node.text!r}")
        if node.kind == "Call" and node.child_count < 1:
            failures.append(f"node {node_id} Call lacks callee")
        if node.kind in ("Let", "Var") and node.child_count not in (1, 2):
            failures.append(f"node {node_id} {node.kind} has invalid arity {node.child_count}")
        if node.kind == "Return" and node.child_count not in (0, 1):
            failures.append(f"node {node_id} Return has invalid arity {node.child_count}")
        if node.start_token < 0 or node.end_token < node.start_token:
            failures.append(f"node {node_id} has invalid half-open token span")
        elif token_count is not None and node.end_token > token_count - 1:
            failures.append(f"node {node_id} token span includes or exceeds EOF")
        if node.line < 1 or node.col < 1:
            failures.append(f"node {node_id} has invalid source anchor")
        elif source is not None and (node.line > max(1, len(source_lines)) or
              (node.line <= len(source_lines) and node.col > len(source_lines[node.line - 1]) + 1)):
            failures.append(f"node {node_id} source anchor is outside input")
        for slot in range(node.first_child, node.first_child + node.child_count):
            if slot in owned_child_slots:
                failures.append(f"children arena slot {slot} is owned more than once")
            owned_child_slots.add(slot)
            child = tree.children[slot]
            if not (0 <= child < len(tree.nodes)):
                failures.append(f"node {node_id} child {child} outside node arena")
            elif child >= node_id:
                failures.append(f"node {node_id} child {child} is not backward")
            else:
                referenced.add(child)
                child_node = tree.nodes[child]
                if child_node.start_token < node.start_token or child_node.end_token > node.end_token:
                    failures.append(f"node {node_id} does not contain child {child}'s token span")
    if owned_child_slots != set(range(len(tree.children))):
        failures.append("children arena contains an unowned slot")
    for node_id, node in enumerate(tree.nodes):
        if (node.first_child < 0 or node.child_count < 0 or
                node.first_child + node.child_count > len(tree.children)):
            continue
        child_ids = tree.children[node.first_child:node.first_child + node.child_count]
        if any(not (0 <= child < len(tree.nodes)) for child in child_ids):
            continue
        child_kinds = [tree.nodes[child].kind for child in child_ids]
        if node.kind in ("Assign", "CompoundAssign") and (not child_kinds or child_kinds[0] != "Identifier"):
            failures.append(f"node {node_id} assignment has a non-name target")
        if node.kind == "CompoundAssign" and node.text not in {"+", "-", "*", "/", "%"}:
            failures.append(f"node {node_id} compound assignment has an invalid operator")
        if node.kind == "Program" and any(kind != "Function" for kind in child_kinds):
            failures.append(f"node {node_id} Program contains a non-Function")
        if node.kind == "Function" and (len(child_kinds) < 2 or child_kinds[-2:] != ["NamedType", "Block"]
                                        or any(kind != "Parameter" for kind in child_kinds[:-2])):
            failures.append(f"node {node_id} Function child order is invalid")
        if node.kind == "Parameter" and child_kinds != ["NamedType"]:
            failures.append(f"node {node_id} Parameter lacks its NamedType")
        if node.kind in ("Let", "Var") and len(child_kinds) == 2 and child_kinds[0] != "NamedType":
            failures.append(f"node {node_id} typed binding does not start with NamedType")
        if node.kind == "Block" and any(kind not in (
                "Let", "Var", "Return", "ExpressionStatement", "FinalExpression", "Assign", "CompoundAssign") for kind in child_kinds):
            failures.append(f"node {node_id} Block contains an invalid child")
        if node.kind == "Block" and (child_kinds.count("FinalExpression") > 1 or
                                     ("FinalExpression" in child_kinds and child_kinds[-1] != "FinalExpression")):
            failures.append(f"node {node_id} Block has a non-final FinalExpression")
    reachable: set[int] = set()
    pending = [tree.root]
    while pending:
        node_id = pending.pop()
        if node_id in reachable or not (0 <= node_id < len(tree.nodes)):
            continue
        reachable.add(node_id)
        node = tree.nodes[node_id]
        if (node.first_child < 0 or node.child_count < 0 or
                node.first_child + node.child_count > len(tree.children)):
            continue
        pending.extend(tree.children[node.first_child:node.first_child + node.child_count])
    if len(reachable) != len(tree.nodes):
        failures.append(f"{len(tree.nodes) - len(reachable)} unreachable node(s)")
    return failures


def normalized(tree: Tree, node_id: int) -> dict[str, object]:
    node = tree.nodes[node_id]
    return {"kind": node.kind, "text": node.text,
            "children": [normalized(tree, child) for child in
                         tree.children[node.first_child:node.first_child + node.child_count]]}


def expected_normalized(value: dict[str, object]) -> dict[str, object]:
    return {"kind": value["kind"], "text": value["text"],
            "children": [expected_normalized(child) for child in value.get("children", [])]}


def check_expected_anchors(tree: Tree, node_id: int, expected: dict[str, object], path: str) -> list[str]:
    failures: list[str] = []
    node = tree.nodes[node_id]
    for field in ("line", "col", "start_token", "end_token"):
        if field in expected and getattr(node, field) != expected[field]:
            failures.append(f"{path}: {field} {getattr(node, field)}, expected {expected[field]}")
    children = tree.children[node.first_child:node.first_child + node.child_count]
    for index, (child_id, child_expected) in enumerate(zip(children, expected.get("children", []))):
        failures.extend(check_expected_anchors(tree, child_id, child_expected, f"{path}/{index}"))
    return failures


def check_cases(cases: list[Case], output: bytes) -> list[str]:
    failures: list[str] = []
    try:
        parsed = parse_output(output)
    except (ValueError, UnicodeDecodeError) as error:
        return [f"invalid dump: {error}"]
    if len(parsed) != len(cases):
        return [f"expected {len(cases)} records, got {len(parsed)}"]
    for index, (case, actual) in enumerate(zip(cases, parsed)):
        if actual.case_id != index:
            failures.append(f"{case.name}: case id {actual.case_id}, expected {index}")
        if case.error is not None:
            if actual.error is None:
                failures.append(f"{case.name}: expected error, got tree")
            else:
                line, col, message = case.error
                if actual.error[:2] != (line, col) or message.lower() not in actual.error[2].lower():
                    failures.append(f"{case.name}: error {actual.error!r}, expected anchor {(line, col)} containing {message!r}")
            continue
        if actual.tree is None:
            failures.append(f"{case.name}: unexpected error {actual.error!r}")
            continue
        arena_failures = validate_tree(actual.tree, case.source, actual.token_count)
        failures.extend(f"{case.name}: {failure}" for failure in arena_failures)
        if case.tree is not None:
            if arena_failures:
                continue
            got = normalized(actual.tree, actual.tree.root)
            want = expected_normalized(case.tree)
            if got != want:
                failures.append(f"{case.name}: normalized tree differs\nwant={want!r}\ngot={got!r}")
            failures.extend(f"{case.name}: {failure}" for failure in
                            check_expected_anchors(actual.tree, actual.tree.root, case.tree, "root"))
    return failures


def run(argv: list[str], timeout: float, cwd: Path = REPO,
        label: str = "command") -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace").encode() if isinstance(error.stdout, str) else (error.stdout or b"")
        stderr = error.stderr.decode(errors="replace").encode() if isinstance(error.stderr, str) else (error.stderr or b"")
        raise EngineFailure(label, argv, f"timed out after {error.timeout}s", stdout, stderr) from error
    except OSError as error:
        raise EngineFailure(label, argv, f"could not launch: {error}", b"", str(error).encode()) from error


def output(label: str, argv: list[str], timeout: float) -> bytes:
    result = run(argv, timeout, label=label)
    if result.returncode != 0 or result.stderr:
        raise EngineFailure(label, argv, f"exit {result.returncode}", result.stdout, result.stderr)
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=REPO / ".build/minivm/minivm")
    parser.add_argument("--sawc", type=Path, default=REPO / "sawc/sawc.py")
    parser.add_argument("--parser", type=Path, default=PARSER,
                        help="parser library to assemble (defaults to prototypes/parser/src/lib.saw)")
    parser.add_argument("--sawc-python", default=sys.executable)
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--vm-budget", type=int, default=80_000_000)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--compile-timeout", type=float, default=300.0)
    parser.add_argument("--no-asan", action="store_true")
    parser.add_argument("--case-prefix", action="append", default=[])
    parser.add_argument("--artifacts", type=Path,
                        help="retain assembled source and complete engine outputs here")
    args = parser.parse_args()
    binary, sawc = args.binary.resolve(), args.sawc.resolve()
    if not binary.is_file() or not sawc.is_file():
        parser.error("--binary and --sawc must name existing files")
    cases = fixture_cases() + generated_cases() + depth_cases()
    if args.case_prefix:
        cases = [case for case in cases if any(case.name.startswith(prefix) for prefix in args.case_prefix)]
    if not cases:
        parser.error("no cases selected")
    with tempfile.TemporaryDirectory(prefix="m18-parser-") as raw_temp:
        temp = Path(raw_temp)
        source = temp / "parser-contract.saw"
        source.write_bytes(assembled_source(cases, args.parser))
        outputs: dict[str, bytes] = {}
        engine_error: EngineFailure | None = None
        try:
            vm = output("VM", [str(binary), "run", str(source), "--budget", str(args.vm_budget)], args.timeout)
            emitted = output("emit", [str(binary), "emit-llvm", str(source)], args.compile_timeout)
            ll = temp / "parser.ll"
            ll.write_bytes(emitted)
            outputs["VM"] = vm
            modes = [("O0", ["-O0"]), ("O2", ["-O2"])]
            if not args.no_asan:
                modes.append(("ASan", ["-O1", "-fsanitize=address"]))
            for name, flags in modes:
                executable = temp / f"parser-{name}"
                compiled = run([args.clang, *flags, str(ll), "-o", str(executable)],
                               args.compile_timeout, label=f"clang {name}")
                if compiled.returncode != 0:
                    argv = [args.clang, *flags, str(ll), "-o", str(executable)]
                    raise EngineFailure(f"clang {name}", argv, f"exit {compiled.returncode}",
                                        compiled.stdout, compiled.stderr)
                outputs[name] = output(name, [str(executable)], args.timeout)
            sawc_executable = temp / "parser-sawc"
            compiled = run([args.sawc_python, str(sawc), str(source), "-o", str(sawc_executable)],
                           args.compile_timeout, label="sawc compile")
            if compiled.returncode != 0:
                argv = [args.sawc_python, str(sawc), str(source), "-o", str(sawc_executable)]
                raise EngineFailure("sawc compile", argv, f"exit {compiled.returncode}",
                                    compiled.stdout, compiled.stderr)
            outputs["sawc"] = output("sawc", [str(sawc_executable)], args.timeout)
            failures = []
            for engine, actual in outputs.items():
                failures.extend(f"{engine}: {failure}" for failure in check_cases(cases, actual))
                if actual != vm:
                    failures.append(f"{engine}: complete dump differs from VM")
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            failures = [str(error)]
            if isinstance(error, EngineFailure):
                engine_error = error
        if failures or args.artifacts:
            artifact = (args.artifacts.resolve() if args.artifacts else
                        REPO / ".build/scratch" / f"parser-failure-{time.time_ns()}")
            artifact.mkdir(parents=True, exist_ok=True)
            (artifact / "source.saw").write_bytes(source.read_bytes())
            if (temp / "parser.ll").is_file():
                (artifact / "parser.ll").write_bytes((temp / "parser.ll").read_bytes())
            for engine, actual in outputs.items():
                (artifact / f"{engine}.out").write_bytes(actual)
            if failures:
                (artifact / "failures.txt").write_text("\n".join(failures) + "\n", encoding="utf-8")
                if engine_error is not None:
                    (artifact / "failure.argv.json").write_text(
                        json.dumps(engine_error.argv, indent=2) + "\n", encoding="utf-8")
                    (artifact / "failure.stdout").write_bytes(engine_error.stdout)
                    (artifact / "failure.stderr").write_bytes(engine_error.stderr)
                failures.append(f"artifacts: {artifact}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print(f"parser AST: {len(cases)} cases passed [VM, O0, O2" +
          ("" if args.no_asan else ", ASan") + ", sawc]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
