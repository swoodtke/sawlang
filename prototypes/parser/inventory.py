#!/usr/bin/env python3
"""Build the deterministic M20 inventory of tracked Saw examples."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
DEFAULT_REPO = HERE.parents[1]


@dataclass(frozen=True)
class Feature:
    name: str
    line: int
    column: int
    evidence: str


ADMITTED_TOKENS = {
    "INT", "STRING", "BOOL", "TRUE", "FALSE", "IDENT", "FUNC", "LET",
    "VAR", "RETURN", "PLUS", "MINUS", "STAR", "SLASH", "PERCENT", "EQ",
    "NEQ", "LT", "GT", "LTE", "GTE", "AND", "OR", "NOT", "LPAREN",
    "RPAREN", "LBRACE", "RBRACE", "COMMA", "COLON", "ARROW", "ASSIGN", "NEWLINE",
    "EOF",
    "PLUS_ASSIGN", "MINUS_ASSIGN", "STAR_ASSIGN", "SLASH_ASSIGN", "PERCENT_ASSIGN",
}

TOKEN_FEATURES = {
    "FLOAT": "float_literal", "INTERP_STRING": "string_interpolation",
    "IF": "control_flow", "ELSE": "control_flow", "GUARD": "control_flow",
    "STRUCT": "type_declaration", "EXTENSION": "extension_declaration",
    "ENUM": "enum_declaration", "MATCH": "match_expression",
    "WHILE": "loop", "FOR": "loop", "BREAK": "loop_control",
    "CONTINUE": "loop_control", "TRAIT": "trait_declaration",
    "EXTERN": "extern_declaration", "STATIC": "static_declaration",
    "MODULE": "module_declaration", "IMPORT": "import_declaration",
    "EXPORT": "export_declaration", "PUBLIC": "visibility_modifier",
    "AT": "attribute", "AMPERSAND": "reference_or_bitwise",
    "PIPE": "bitwise_operator", "CARET": "bitwise_operator",
    "TILDE": "bitwise_operator", "MOVE": "move_expression",
    "QUESTION": "optional_syntax",
    "DOUBLE_QUESTION": "optional_syntax", "EXCLAIM": "force_unwrap",
    "QUESTION_DOT": "optional_chain", "DOT": "member_or_tuple_access",
    "LBRACKET": "collection_or_index", "RBRACKET": "collection_or_index",
    "DOTDOT": "range", "DOTDOT_EQ": "range", "SEMICOLON": "semicolon",
    "HASH_DIRECTIVE": "source_location_literal", "DOLLAR_PARAM": "closure",
    "TRY": "result_control", "CATCH": "result_control", "AS": "cast",
    "UNSAFE": "effect_modifier", "BORROWS": "effect_modifier",
    "LEND": "lend", "SELF": "self_expression", "NONE": "none_literal",
    "CASE": "enum_or_match_case", "IN": "loop", "INIT": "initializer_declaration",
    "PLUS_ASSIGN": "compound_assignment", "MINUS_ASSIGN": "compound_assignment",
    "STAR_ASSIGN": "compound_assignment", "SLASH_ASSIGN": "compound_assignment",
    "PERCENT_ASSIGN": "compound_assignment", "AMP_ASSIGN": "compound_assignment",
    "PIPE_ASSIGN": "compound_assignment", "CARET_ASSIGN": "compound_assignment",
    "SHL_ASSIGN": "compound_assignment", "SHR_ASSIGN": "compound_assignment",
    "WRAP_ADD": "wrapping_operator", "WRAP_SUB": "wrapping_operator",
    "WRAP_MUL": "wrapping_operator", "ELLIPSIS": "variadic_parameter",
}


def _load_compiler(repo: Path):
    sys.path.insert(0, str(repo / "sawc"))
    from lexer import Lexer  # type: ignore
    from parser import Parser  # type: ignore
    import ast_nodes  # type: ignore
    return Lexer, Parser, ast_nodes


def tracked_examples(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "examples/*.saw", "examples/**/*.saw"],
        cwd=repo, check=True, capture_output=True,
    )
    return sorted({item.decode("utf-8") for item in result.stdout.split(b"\0") if item})


def _location(node: Any) -> tuple[int, int]:
    return int(getattr(node, "line", 1) or 1), int(getattr(node, "column", 1) or 1)


def _feature(name: str, node: Any, evidence: str) -> Feature:
    line, column = _location(node)
    return Feature(name, line, column, evidence)


def _named_type(value: Any) -> bool:
    if value is None:
        return False
    return not getattr(value, "type_args", None) and value.kind.name in {
        "INT", "UINT", "FLOAT", "BOOL", "STRING", "VOID", "STRUCT", "ENUM",
        "TYPE_PARAM", "SELF", "NEVER", "INT8", "INT16", "INT32", "INT64",
        "UINT8", "UINT16", "UINT32", "UINT64",
    }


KNOWN_EXPRESSION_NODES = {
    "FloatLiteral", "StringInterpolation", "FormatPlaceholder", "MoveExpr",
    "ReferenceExpr", "CastExpr", "IfExpr", "TupleLiteral", "TupleIndex",
    "ArrayLiteral", "MapLiteral", "SetLiteral", "ArrayIndex", "MemberAccess",
    "StructInit", "NoneLiteral", "SourceLocationLiteral", "LendVarLiteral",
    "ForceUnwrap", "NilCoalesce", "OptionalChain", "BindOptional",
    "OptionalEvalExpr", "OptionalChainAssign", "OptionalWrap", "ResultOkWrap",
    "ResultErrWrap", "ErasedErrWrap", "TryExpr", "TryCatchExpr", "MethodCall",
    "SelfExpr", "IfLetExpr", "EnumInit", "MatchExpr", "RangeExpr", "ClosureExpr",
    "WhileExpr", "ForLoop",
}
KNOWN_STATEMENT_NODES = {
    "AssignStatement", "CompoundAssignStatement", "BreakStatement",
    "ContinueStatement", "ForLoop", "GuardLetStatement", "LendStatement",
    "WhileExpr", "DestructuringLet", "StaticAssert",
}


def ast_features(program: Any, ast: Any) -> tuple[list[Feature], list[Feature]]:
    """Return every observed AST feature outside M20, without first-match hiding."""
    features: list[Feature] = []
    unresolved: list[Feature] = []
    declaration_fields = {
        "structs": "type_declaration", "extensions": "extension_declaration",
        "enums": "enum_declaration", "traits": "trait_declaration",
        "type_definitions": "type_definition", "extern_blocks": "extern_declaration",
        "statics": "static_declaration", "imports": "import_declaration",
        "module_decls": "module_declaration", "exports": "export_declaration",
        "static_asserts": "static_assert",
    }
    for field, name in declaration_fields.items():
        for node in getattr(program, field, None) or []:
            features.append(_feature(name, node, type(node).__name__))
    if getattr(program, "module_doc", None):
        features.append(Feature("documentation_comment", 1, 1, "module_doc"))

    allowed_expr = (ast.IntLiteral, ast.StringLiteral, ast.BoolLiteral,
                    ast.Identifier, ast.UnaryOp, ast.BinaryOp, ast.FunctionCall)
    allowed_ops = {"+", "-", "*", "/", "%", "<", "<=", ">", ">=",
                   "==", "!=", "&&", "||"}

    def expression(value: Any) -> None:
        if not isinstance(value, allowed_expr):
            node_name = type(value).__name__
            target = features if node_name in KNOWN_EXPRESSION_NODES else unresolved
            target.append(_feature("expression" if target is features else "unknown_ast_node",
                                   value, node_name))
            return
        if isinstance(value, ast.FunctionCall):
            if getattr(value, "type_args", None):
                features.append(_feature("generic_call", value, "type_args"))
            for argument in value.arguments:
                if argument.name is not None:
                    features.append(_feature("labelled_argument", argument.value, argument.name))
                expression(argument.value)
        elif isinstance(value, ast.UnaryOp):
            if value.op not in {"-", "not"}:
                features.append(_feature("unary_operator", value, value.op))
            expression(value.operand)
        elif isinstance(value, ast.BinaryOp):
            if value.op not in allowed_ops:
                features.append(_feature("binary_operator", value, value.op))
            expression(value.left)
            expression(value.right)

    allowed_stmt = (ast.LetStatement, ast.ReturnStatement, ast.ExpressionStatement,
                    ast.AssignStatement, ast.CompoundAssignStatement)
    for function in program.functions:
        for field, name in (("type_params", "generic_function"),
                            ("attributes", "attribute")):
            if getattr(function, field, None):
                features.append(_feature(name, function, field))
        if getattr(function, "doc", None):
            features.append(_feature("documentation_comment", function, "function doc"))
        visibility = getattr(function, "visibility", None)
        if visibility is not None and getattr(visibility, "name", "PRIVATE") != "PRIVATE":
            features.append(_feature("visibility_modifier", function, visibility.name))
        for field in ("is_sync", "is_unsafe", "is_borrows"):
            if getattr(function, field, False):
                features.append(_feature("effect_modifier", function, field))
        if not _named_type(function.return_type):
            features.append(_feature("composite_return_type", function, str(function.return_type)))
        for parameter in function.parameters:
            if getattr(parameter, "default_value", None) is not None:
                features.append(_feature("default_parameter", parameter, parameter.name))
            if getattr(parameter, "is_reference", False):
                features.append(_feature("reference_parameter", parameter, parameter.name))
            if not _named_type(parameter.type):
                features.append(_feature("composite_parameter_type", parameter, parameter.name))
        for statement in function.body.statements:
            if not isinstance(statement, allowed_stmt):
                node_name = type(statement).__name__
                target = features if node_name in KNOWN_STATEMENT_NODES else unresolved
                target.append(_feature("statement" if target is features else "unknown_ast_node",
                                       statement, node_name))
                continue
            if isinstance(statement, (ast.AssignStatement, ast.CompoundAssignStatement)):
                if not isinstance(statement.target, ast.Identifier):
                    features.append(_feature("assignment_target", statement.target,
                                             type(statement.target).__name__))
                if (isinstance(statement, ast.CompoundAssignStatement) and
                        statement.op not in {"+", "-", "*", "/", "%"}):
                    features.append(_feature("compound_assignment_operator", statement, statement.op))
                expression(statement.target)
                expression(statement.value)
            elif isinstance(statement, ast.LetStatement):
                if getattr(statement, "attributes", None):
                    features.append(_feature("attribute", statement, "binding attribute"))
                if statement.type_annotation is not None and not _named_type(statement.type_annotation):
                    features.append(_feature("composite_binding_type", statement, str(statement.type_annotation)))
                expression(statement.value)
            elif isinstance(statement, ast.ReturnStatement):
                if statement.value is not None:
                    expression(statement.value)
            else:
                expression(statement.expression)
        if function.body.final_expr is not None:
            expression(function.body.final_expr)
    return features, unresolved


def source_features(tokens: list[Any], doc_comments: list[Any]) -> tuple[list[Feature], list[Feature]]:
    unsupported: list[Feature] = []
    unresolved: list[Feature] = []
    for comment in doc_comments:
        unsupported.append(Feature("documentation_comment", int(comment.line),
                                   int(comment.column), getattr(comment, "kind", "doc")))
    for token in tokens:
        kind = token.type.name
        if kind in ADMITTED_TOKENS:
            continue
        name = TOKEN_FEATURES.get(kind)
        feature = Feature(name or "unknown_token", int(token.line), int(token.column), kind)
        (unsupported if name else unresolved).append(feature)
    # The production parser currently loses the postfix call funnel in these
    # shapes (SL-73), so its AST cannot prove that they are admitted.
    significant = [token for token in tokens if token.type.name != "EOF"]
    for left, right in zip(significant, significant[1:]):
        if left.type.name == "RPAREN" and right.type.name == "LPAREN":
            unresolved.append(Feature("postfix_call_after_group_or_call", int(right.line),
                                      int(right.column), "SL-73"))
    return unsupported, unresolved


def feature_records(features: list[Feature]) -> list[dict[str, Any]]:
    """Keep first located evidence plus a count, rather than ballooning JSON."""
    first: dict[str, Feature] = {}
    counts: Counter[str] = Counter()
    for feature in features:
        first.setdefault(feature.name, feature)
        counts[feature.name] += 1
    return [{**asdict(feature), "occurrences": counts[name]}
            for name, feature in first.items()]


def semantic_directives(source: str) -> tuple[list[str], bool]:
    directives = [line.strip() for line in source.splitlines()
                  if re.match(r"\s*//\s*(?:XFAIL|EXPECT(?:-|:))", line)]
    negative = any(re.search(r"EXPECT-[A-Z-]*ERROR\b|EXPECT:\s*(?:error|compile error)\b",
                             line, re.IGNORECASE) for line in directives)
    return directives, negative


def classify_file(repo: Path, relative: str, compiler: tuple[Any, Any, Any]) -> dict[str, Any]:
    Lexer, Parser, ast = compiler
    raw = (repo / relative).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    directives: list[str] = []
    negative = False
    try:
        source = raw.decode("utf-8")
        directives, negative = semantic_directives(source)
    except UnicodeDecodeError as error:
        return {"path": relative, "sha256": digest, "scope": "top" if relative.count("/") == 1 else "nested",
                "classification": "parse_error", "parser_verdict": "not_run",
                "features": feature_records([Feature("invalid_utf8", 1, error.start + 1, str(error))]),
                "semantic_expect": {"negative": False, "directives": []}}
    try:
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        program = Parser(tokens, source_file=relative, doc_comments=lexer.doc_comments).parse()
    except SyntaxError as error:
        match = re.search(r"at (\d+):(\d+): (.*)", str(error), re.DOTALL)
        line = int(match.group(1)) if match else 0
        column = int(match.group(2)) if match else 0
        message = match.group(3).splitlines()[0] if match else str(error).splitlines()[0]
        return {"path": relative, "sha256": digest, "scope": "top" if relative.count("/") == 1 else "nested",
                "classification": "parse_error", "parser_verdict": "rejected",
                "features": feature_records([Feature("python_parse_error", line, column, message)]),
                "semantic_expect": {"negative": negative, "directives": directives}}
    except Exception as error:
        return {"path": relative, "sha256": digest, "scope": "top" if relative.count("/") == 1 else "nested",
                "classification": "oracle_failure", "parser_verdict": "failed",
                "features": feature_records([Feature(type(error).__name__, 1, 1, str(error).splitlines()[0])]),
                "semantic_expect": {"negative": negative, "directives": directives}}

    unsupported, unresolved = source_features(tokens, lexer.doc_comments)
    ast_unsupported, ast_unresolved = ast_features(program, ast)
    unsupported.extend(ast_unsupported)
    unresolved.extend(ast_unresolved)
    # Stable de-duplication retains source order and all distinct locations.
    unsupported = list(dict.fromkeys(unsupported))
    unresolved = list(dict.fromkeys(unresolved))
    if unresolved:
        classification = "unresolved"
        features = unresolved + unsupported
    elif unsupported:
        classification = "unsupported"
        features = unsupported
    else:
        classification = "candidate"
        features = []
    return {"path": relative, "sha256": digest,
            "scope": "top" if relative.count("/") == 1 else "nested",
            "classification": classification, "parser_verdict": "accepted",
            "features": feature_records(features),
            "semantic_expect": {"negative": negative, "directives": directives}}


def build_inventory(repo: Path) -> dict[str, Any]:
    compiler = _load_compiler(repo)
    rows = [classify_file(repo, path, compiler) for path in tracked_examples(repo)]
    counts = Counter(row["classification"] for row in rows)
    top = Counter(row["classification"] for row in rows if row["scope"] == "top")
    nested = Counter(row["classification"] for row in rows if row["scope"] == "nested")
    return {"version": 1, "corpus": "git ls-files examples/*.saw examples/**/*.saw",
            "counts": {"total": len(rows), "top": sum(top.values()), "nested": sum(nested.values()),
                       "by_classification": dict(sorted(counts.items())),
                       "top_by_classification": dict(sorted(top.items())),
                       "nested_by_classification": dict(sorted(nested.items()))},
            "examples": rows}


def report(inventory: dict[str, Any]) -> str:
    counts = inventory["counts"]
    lines = ["# M20 examples parser inventory", "",
             "Generated by `prototypes/parser/inventory.py`; do not edit by hand.", "",
             f"Tracked examples: **{counts['total']}** (**{counts['top']}** top-level, **{counts['nested']}** nested).",
             "", "| Classification | All | Top-level | Nested |", "|---|---:|---:|---:|"]
    names = sorted(set(counts["by_classification"]) | set(counts["top_by_classification"]) |
                   set(counts["nested_by_classification"]))
    for name in names:
        lines.append(f"| `{name}` | {counts['by_classification'].get(name, 0)} | "
                     f"{counts['top_by_classification'].get(name, 0)} | "
                     f"{counts['nested_by_classification'].get(name, 0)} |")
    rows = inventory["examples"]
    candidate_rows = [row for row in rows if row["classification"] == "candidate"]
    negative_candidates = sum(bool(row["semantic_expect"]["negative"]) for row in candidate_rows)
    feature_counts = Counter()
    for row in rows:
        for feature in row["features"]:
            feature_counts[feature["name"]] += feature["occurrences"]
    lines += ["", "`candidate` means both the source/token audit and Python AST whitelist fit M20.",
              "It is input to review, not frozen differential eligibility. `unresolved` is never",
              "silently counted as supported. Semantic EXPECT directives are recorded independently",
              "for each file and do not affect these classifications.", "",
              f"Candidate semantic negatives: **{negative_candidates}** of **{len(candidate_rows)}**.",
              "", "## Candidate paths", ""]
    lines.extend(f"- `{row['path']}`" for row in candidate_rows)
    lines += ["", "## Most common unsupported or unresolved features", "",
              "Feature counts are occurrences by file record, not an exclusive first-reason partition.", "",
              "| Feature | Occurrences |", "|---|---:|"]
    for name, count in feature_counts.most_common(20):
        lines.append(f"| `{name}` | {count} |")
    unresolved_rows = [row for row in rows if row["classification"] == "unresolved"]
    if unresolved_rows:
        lines += ["", "## Unresolved paths", ""]
        lines.extend(f"- `{row['path']}`" for row in unresolved_rows)
    lines.append("")
    return "\n".join(lines)


EXAMPLE_COLUMNS = ["path", "sha256", "scope_code", "classification_code",
                   "parser_verdict_code", "features", "semantic_expect"]
FEATURE_COLUMNS = ["name_string", "line", "column", "evidence_string", "occurrences"]
SEMANTIC_COLUMNS = ["negative", "directive_strings"]
SCOPE_CODES = ["top", "nested"]
CLASSIFICATION_CODES = ["candidate", "unsupported", "parse_error", "oracle_failure", "unresolved"]
VERDICT_CODES = ["accepted", "rejected", "failed", "not_run"]


def _string_table(values: list[str]) -> tuple[list[str], dict[str, int]]:
    table = sorted(set(values))
    return table, {value: index for index, value in enumerate(table)}


def encode_snapshot(inventory: dict[str, Any]) -> dict[str, Any]:
    """Losslessly encode the rich inventory into the compact snapshot schema."""
    rows = inventory["examples"]
    feature_names, feature_ids = _string_table(
        [feature["name"] for row in rows for feature in row["features"]])
    evidence, evidence_ids = _string_table(
        [feature["evidence"] for row in rows for feature in row["features"]])
    directives, directive_ids = _string_table(
        [item for row in rows for item in row["semantic_expect"]["directives"]])
    encoded_rows = []
    for row in rows:
        features = [[feature_ids[item["name"]], item["line"], item["column"],
                     evidence_ids[item["evidence"]], item["occurrences"]]
                    for item in row["features"]]
        semantic = [row["semantic_expect"]["negative"],
                    [directive_ids[item] for item in row["semantic_expect"]["directives"]]]
        encoded_rows.append([
            row["path"], row["sha256"], SCOPE_CODES.index(row["scope"]),
            CLASSIFICATION_CODES.index(row["classification"]),
            VERDICT_CODES.index(row["parser_verdict"]), features, semantic,
        ])
    return {
        "snapshot_version": 2,
        "inventory_version": inventory["version"],
        "corpus": inventory["corpus"],
        "counts": inventory["counts"],
        "schema": {"example_columns": EXAMPLE_COLUMNS, "feature_columns": FEATURE_COLUMNS,
                   "semantic_columns": SEMANTIC_COLUMNS, "scope_codes": SCOPE_CODES,
                   "classification_codes": CLASSIFICATION_CODES,
                   "parser_verdict_codes": VERDICT_CODES},
        "strings": {"feature_names": feature_names, "evidence": evidence,
                    "directives": directives},
        "examples": encoded_rows,
    }


def decode_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Decode schema v2 and reject column/code drift rather than guessing."""
    if snapshot.get("snapshot_version") != 2:
        raise ValueError("parser inventory requires snapshot_version 2")
    schema = snapshot.get("schema", {})
    expected = {"example_columns": EXAMPLE_COLUMNS, "feature_columns": FEATURE_COLUMNS,
                "semantic_columns": SEMANTIC_COLUMNS, "scope_codes": SCOPE_CODES,
                "classification_codes": CLASSIFICATION_CODES,
                "parser_verdict_codes": VERDICT_CODES}
    if schema != expected:
        raise ValueError("parser inventory schema columns or codes do not match")
    strings = snapshot["strings"]
    rows = []
    def table_value(table: list[Any], index: Any) -> Any:
        if type(index) is not int or index < 0 or index >= len(table):
            raise ValueError("snapshot table index out of range")
        return table[index]

    try:
        for encoded in snapshot["examples"]:
            if type(encoded) is not list or len(encoded) != len(EXAMPLE_COLUMNS):
                raise ValueError("wrong example record width")
            path, digest, scope, classification, verdict, encoded_features, encoded_semantic = encoded
            if any(type(item) is not list or len(item) != len(FEATURE_COLUMNS)
                   for item in encoded_features):
                raise ValueError("wrong feature record width")
            if type(encoded_semantic) is not list or len(encoded_semantic) != len(SEMANTIC_COLUMNS):
                raise ValueError("wrong semantic record width")
            features = [{"name": table_value(strings["feature_names"], item[0]), "line": item[1],
                         "column": item[2], "evidence": table_value(strings["evidence"], item[3]),
                         "occurrences": item[4]} for item in encoded_features]
            semantic = {"negative": encoded_semantic[0],
                        "directives": [table_value(strings["directives"], item)
                                       for item in encoded_semantic[1]]}
            rows.append({"path": path, "sha256": digest, "scope": table_value(SCOPE_CODES, scope),
                         "classification": table_value(CLASSIFICATION_CODES, classification),
                         "parser_verdict": table_value(VERDICT_CODES, verdict), "features": features,
                         "semantic_expect": semantic})
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise ValueError("malformed parser inventory snapshot record") from error
    return {"version": snapshot["inventory_version"], "corpus": snapshot["corpus"],
            "counts": snapshot["counts"], "examples": rows}


def render_json(inventory: dict[str, Any]) -> str:
    """Render schema-v2 JSON with one compact example record per line."""
    snapshot = encode_snapshot(inventory)
    rows = snapshot.pop("examples")
    prefix = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    lines = [prefix[:-1] + ',"examples":[']
    for index, row in enumerate(rows):
        suffix = "," if index + 1 < len(rows) else ""
        lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + suffix)
    lines += ["]}"]
    return "\n".join(lines) + "\n"


def snapshots_current(inventory: dict[str, Any], output: Path, report_path: Path) -> bool:
    expected_json = render_json(inventory)
    expected_report = report(inventory)
    try:
        return (output.read_text(encoding="utf-8") == expected_json and
                report_path.read_text(encoding="utf-8") == expected_report)
    except FileNotFoundError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--output", type=Path, default=HERE / "examples_inventory.json")
    parser.add_argument("--report", type=Path, default=HERE / "examples_inventory.md")
    parser.add_argument("--check", action="store_true",
                        help="fail if the checked-in inventory snapshots are stale")
    args = parser.parse_args()
    inventory = build_inventory(args.repo.resolve())
    if args.check:
        if snapshots_current(inventory, args.output, args.report):
            return 0
        print("parser inventory snapshots are stale; regenerate with inventory.py", file=sys.stderr)
        return 1
    args.output.write_text(render_json(inventory), encoding="utf-8")
    args.report.write_text(report(inventory), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
