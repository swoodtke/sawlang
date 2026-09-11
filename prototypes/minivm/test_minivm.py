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
# Python sawc also builds runtime objects in a fresh checkout.
SAWC_COMPILE_TIMEOUT = 180


@dataclass(frozen=True)
class RunCase:
    name: str
    stdout: str
    exit_code: int = 0
    section: str = "core"
    compare_sawc: bool = False


@dataclass(frozen=True)
class RejectCase:
    name: str
    message: str
    section: str = "core"
    compare_sawc: bool = False


RUN_CASES = (
    RunCase("unsigned_parse/radices", "42\n" * 7 + "1295\n42\n42\n43323\n11\nnone\nnone\n0\n0\n", section="unsigned_parse", compare_sawc=True),
    RunCase("unsigned_parse/boundaries", "9223372036854775808\n18446744073709551614\n18446744073709551615\nnone\n18446744073709551614\n18446744073709551615\nnone\n18446744073709551615\nnone\n18446744073709551615\nnone\n18446744073709551615\nnone\n18446744073709551615\n", section="unsigned_parse", compare_sawc=True),
    RunCase("unsigned_parse/invalid", "none\n" * 21, section="unsigned_parse", compare_sawc=True),
    RunCase("unsigned_parse/receivers", "123\n42\n123\n", section="unsigned_parse", compare_sawc=True),
    RunCase("unsigned_parse/receiver_snapshot", "255\nbad\n", section="unsigned_parse", compare_sawc=True),
    RunCase("unsigned_parse/literal_fits", "true\nfalse\n" * 7 + "false\nfalse\n", section="unsigned_parse", compare_sawc=True),
    RunCase("results/review_composition", "hello\n7\n0\nkept\n5\nbad\n", section="results"),
    RunCase("results/construction_wrapping", "7\nbad\n255\n9\n9\n11\nexplicit\n", section="results"),
    RunCase("results/nested_optional", "inner-none\nouter-none\n7\ninner\n", section="results"),
    RunCase("results/same_type_explicit", "42\n999\n", section="results"),
    RunCase("results/void_success", "ok\nfailed\n", section="results"),
    RunCase("results/match_snapshot_ownership", "subject\nold\nsaved\nchanged\n", section="results"),
    RunCase("results/try_propagation", "later\nleaf\n8\nstop\n", section="results"),
    RunCase("results/try_nested_success", "7\n", section="results"),
    RunCase("results/try_panic", "runtime error: try! failed\n", 1, "results"),
    RunCase("results/loop_cleanup", "early\n200\n", section="results"),
    RunCase("results/value_match_control", "8\n-1\nkept\nfailure\n", section="results"),
    RunCase("results/value_match_widening", "64\n-8\n16\n", section="results"),
    RunCase("results/try_void", "after\npropagated\nstopped\nforced\n", section="results"),
    RunCase("optionals/review_nested_context", "chosen\nsome-none\nnested-none\n", section="optionals"),
    RunCase("optionals/basic_numeric", "7\nnone\n255\n", section="optionals"),
    RunCase("optionals/nested_semantics", "outer-none\ninner-none\n9\nbranch-inner-none\n7\n18446744073709551615\n", section="optionals"),
    RunCase("optionals/contextual_calls_arms", "255\nnone\na\nchain\nignored\n", section="optionals"),
    RunCase("optionals/string_record_payload", "alpha\nalpha\nnone\n", section="optionals"),
    RunCase("optionals/references_methods", "start\nnext\nnone\n", section="optionals"),
    RunCase("optionals/binding_snapshot_shadow", "old\nnew\nchanged\nold\n", section="optionals"),
    RunCase("optionals/value_binding_subject_once", "subject\nyes\nsubject\nfallback\n", section="optionals"),
    RunCase("optionals/early_return_loop_cleanup", "early\nodd\n199\n", section="optionals"),
    RunCase("optionals/token_tok_extract", "word\n4\n9\nnone\n", section="optionals"),
    RunCase("owning_records/copy_replace_nested", "alpha\ninner\nbeta\nchanged\n", section="owning_records"),
    RunCase("owning_records/references_methods_abi", "left\nright\nnext\nfield\n9\n", section="owning_records"),
    RunCase("owning_records/value_control_cleanup", "then\n1\nred\n2\nearly\n3\n", section="owning_records"),
    RunCase("owning_records/loop_cleanup", "odd\n199\n", section="owning_records"),
    RunCase("owning_records/string_match", "1\n2\n3\n4\n5\n6\n7\n", section="owning_records"),
    RunCase("owning_records/string_match_snapshot", "old\nchanged\n", section="owning_records"),
    RunCase("owning_records/keyword_suffix_extract", "true\n" * 49, section="owning_records"),
    RunCase("owning_records/lexer_advance_extract", "65\n1\n1\n2\n10\n2\n2\n1\n195\n3\n2\n2\n169\n4\n2\n2\n-1\n", section="owning_records"),
    RunCase("strings/literals_escapes", "\nASCII\ncafé🙂\na\x00b\n{left} \\ right\n\x01x\n", section="strings"),
    RunCase("strings/intrinsics", "0\ntrue\n5\nfalse\n104\n111\n101\n169\n\n\nhello\ntrue\ntrue\ntrue\ntrue\n", section="strings"),
    RunCase("strings/brace_marker_provenance", "1\n123\n2\n1\n123\n1\n125\n2\n1\n125\n", section="strings"),
    RunCase("strings/copies_calls_results", "alpha\nalpha\nbeta\nbeta\nright\n", section="strings"),
    RunCase("strings/references", "before\nbefore\nafter\nafter\n", section="strings"),
    RunCase("strings/receiver_snapshot_order", "true\nafter\n", section="strings"),
    RunCase("strings/temporary_intrinsics", "3\ntrue\nell\n2\n1\n195\n", section="strings"),
    RunCase("strings/repeated_allocations", "final\n500\n", section="strings"),
    RunCase("strings/recursive_results", "cdef\n4\n", section="strings"),
    RunCase("strings/value_if_nested_cleanup", "then\nelse\n", section="strings"),
    RunCase("strings/value_if_early_return_cleanup", "kept\nearly\nother\n", section="strings"),
    RunCase("strings/value_if_loop_cleanup", "odd\n200\n", section="strings"),
    RunCase("strings/index_negative", "runtime error: string index out of range\n", 1, "strings"),
    RunCase("strings/index_at_end", "runtime error: string index out of range\n", 1, "strings"),
    RunCase("strings/index_huge", "runtime error: string index out of range\n", 1, "strings"),
    RunCase("strings/range_negative", "runtime error: string range out of bounds\n", 1, "strings"),
    RunCase("strings/range_reversed", "runtime error: string range out of bounds\n", 1, "strings"),
    RunCase("strings/range_past_end", "runtime error: string range out of bounds\n", 1, "strings"),
    RunCase("strings/range_huge", "runtime error: string range out of bounds\n", 1, "strings"),
    RunCase("receivers/whole_record_reference", "1\n2\n3\n4\n9\n8\n", section="receivers"),
    RunCase("receivers/nested_forwarding", "7\n13\n18\n", section="receivers"),
    RunCase("receivers/mixed_abi", "5\n6\n9\n10\n", section="receivers"),
    RunCase("receivers/recursive_growth", "41\n42\n", section="receivers"),
    RunCase("receivers/methods_basic", "5\n11\n11\n", section="receivers"),
    RunCase("receivers/methods_lookup_labels", "13\n22\n18\n", section="receivers"),
    RunCase("receivers/nested_method_forward", "3\n7\n", section="receivers"),
    RunCase("receivers/lexer_advance", "1\n2\n2\n3\n2\n2\n", section="receivers"),
    RunCase("references/read_mutate_compound", "41\n42\n51\n25\n5\n", section="references"),
    RunCase("references/scalar_kinds", "18446744073709551615\n255\ntrue\ntrue\n", section="references"),
    RunCase("references/direct_record_fields", "8\n21\n", section="references"),
    RunCase("references/shared_aliases", "18\n9\n", section="references"),
    RunCase("references/forwarding_growth", "38\n38\n", section="references"),
    RunCase("references/mutable_to_shared", "12\n13\n", section="references"),
    RunCase("references/value_before_borrow", "4\n10\n11\n", section="references"),
    RunCase("references/mixed_record_reference", "5\n12\n9\n16\n", section="references"),
    RunCase("references/assignment_rhs_nonborrow", "3\n6\n4\n8\n", section="references"),
    RunCase("references/nested_borrow_release", "7\n11\n", section="references"),
    RunCase("enums/nested_control", "true\n10\n11\n20\n", section="enums"),
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
    RunCase("enums/values_copy_equality", "true\nfalse\ntrue\ntrue\n", section="enums"),
    RunCase("enums/calls_returns_forward", "true\ntrue\n", section="enums"),
    RunCase("enums/record_fields", "true\ntrue\ntrue\n3\n", section="enums"),
    RunCase("enums/match_unqualified", "1\n2\n3\n", section="enums"),
    RunCase("enums/match_qualified", "true\nfalse\n", section="enums"),
    RunCase("enums/match_wildcard", "10\n99\n99\n", section="enums"),
    RunCase("enums/subject_once", "7\n2\n", section="enums"),
    RunCase("enums/all_arms_return", "20\n40\n60\n", section="enums"),
    RunCase("enums/lexer_token_kind", "1\n2\n3\ntrue\n", section="enums"),
    RunCase("values/scalar_bool_tails", "42\ntrue\n-128\n", section="values"),
    RunCase("values/if_nested", "11\n12\n21\n22\n", section="values"),
    RunCase("values/else_if", "-1\n0\n1\n2\n", section="values"),
    RunCase("values/match_arms", "1\n3\n11\n22\n33\n", section="values"),
    RunCase("values/record_enum_values", "7\ntrue\n9\ntrue\ntrue\n", section="values"),
    RunCase("values/contexts", "-7\n5\n-128\n4294967295\n65535\n", section="values"),
    RunCase("values/evaluation_order", "1\n2\n20\n4\n5\n50\n", section="values"),
    RunCase("values/match_subject_once", "6\n20\n", section="values"),
    RunCase("values/returns_and_scope", "10\n20\n30\n40\n3\n9\n50\n", section="values"),
    RunCase("values/u64_context", "18446744073709551615\n9223372036854775808\n255\n", section="values"),
    RunCase("values/lexer_hex_value", "0\n9\n10\n15\n10\n15\n", section="values"),
    RunCase("values/inference_order_widening", "6\n-3\n-1\n1\n2\n8\n42\n", section="values"),
    RunCase("values/review_grid", "10\n11\n18446744073709551615\n10\n12\n9223372036854775808\n20\n20\n18446744073709551615\n30\n30\n99\n40\n43\n9223372036854775808\n46\n", section="values"),
    RunCase("values/review_context", "true\nfalse\n2\n1\n3\n5\n3\n40\n7\n", section="values"),
    RunCase("values/review_composition", "true\n9\n8\n11\n255\n1\n", section="values"),
    RunCase("values/statement_else_if", "2\n3\n5\n6\n7\n", section="values"),
    RunCase("values/value_block_void_then_tail", "10\n42\n", section="values"),
    RunCase("values/parenthesized_argument_block", "0\n1\n8\n42\n", section="values"),
)

REJECT_CASES = (
    RejectCase("unsigned_parse/reject_radix_type", "argument must be Int", "unsigned_parse", True),
    RejectCase("unsigned_parse/reject_arity", "wrong number of arguments", "unsigned_parse", True),
    RejectCase("unsigned_parse/reject_label", "does not match parameter", "unsigned_parse", True),
    RejectCase("unsigned_parse/reject_result_type", "cannot implicitly convert", "unsigned_parse", True),
    RejectCase("results/reject_ambiguous_same_type", "ambiguous Result auto-wrap", "results"),
    RejectCase("results/reject_ambiguous_literal", "ambiguous Result auto-wrap", "results"),
    RejectCase("results/reject_none_non_optional", "None requires an expected Optional type", "results"),
    RejectCase("results/reject_void_return_none", "None requires an expected Optional type", "results"),
    RejectCase("results/reject_void_error", "Result error type cannot be Void", "results"),
    RejectCase("results/reject_type_arity", "Result requires exactly two type arguments", "results"),
    RejectCase("results/reject_reference_payload", "Result reference payloads are not supported", "results"),
    RejectCase("results/reject_constructor_label", "argument label", "results"),
    RejectCase("results/reject_constructor_arity", "Result.Err requires an error payload", "results"),
    RejectCase("results/reject_void_constructor", "Result.Ok requires a value payload", "results"),
    RejectCase("results/reject_match_duplicate", "duplicate Result match arm", "results"),
    RejectCase("results/reject_match_missing", "non-exhaustive Result match", "results"),
    RejectCase("results/reject_match_payload_arity", "Result Ok pattern requires a payload", "results"),
    RejectCase("results/reject_try_non_result", "try operand must be a Result", "results"),
    RejectCase("results/reject_try_context", "try requires a Result-returning function", "results"),
    RejectCase("results/reject_try_error_type", "try error type does not match function result", "results"),
    RejectCase("optionals/reject_uncontextualized_none", "None requires an expected Optional type", "optionals"),
    RejectCase("optionals/reject_if_let_non_optional", "if binding requires an Optional value", "optionals"),
    RejectCase("optionals/reject_binding_scope", "unknown name", "optionals"),
    RejectCase("optionals/reject_coalescing", "optional coalescing `??` is not supported", "optionals"),
    RejectCase("optionals/reject_chaining", "optional chaining `?.` is not supported", "optionals"),
    RejectCase("optionals/reject_force_unwrap", "optional force unwrap `!` is not supported", "optionals"),
    RejectCase("optionals/reject_optional_void", "Optional<Void> is not supported", "optionals"),
    RejectCase("optionals/reject_value_binding_missing_tail", "continuing value branch requires a tail expression", "optionals"),
    RejectCase("optionals/reject_numeric_range", "integer literal does not fit UInt8", "optionals"),
    RejectCase("owning_records/reject_string_match_duplicate", "duplicate String match pattern", "owning_records"),
    RejectCase("owning_records/reject_string_match_non_string", "String match patterns must be String literals or `_`", "owning_records"),
    RejectCase("owning_records/reject_string_match_interpolation", "string interpolation is not supported in match patterns", "owning_records"),
    RejectCase("owning_records/reject_string_match_no_wildcard", "String match requires a final wildcard", "owning_records"),
    RejectCase("strings/reject_interpolation", "string interpolation is not supported", "strings"),
    RejectCase("strings/reject_arithmetic", "arithmetic requires integer operands", "strings"),
    RejectCase("strings/reject_cast", "`as` requires integer source and target types", "strings"),
    RejectCase("strings/reject_static", "String statics are not supported", "strings"),
    RejectCase("strings/reject_unknown_intrinsic", "unknown String intrinsic", "strings"),
    RejectCase("strings/reject_intrinsic_label", "argument label", "strings"),
    RejectCase("strings/reject_intrinsic_arity", "wrong number of arguments to String.substring", "strings"),
    RejectCase("strings/reject_intrinsic_type", "String.byte_at", "strings"),
    RejectCase("receivers/reject_write_shared_record", "cannot assign through a shared reference", "receivers"),
    RejectCase("receivers/reject_immutable_record_borrow", "cannot mutably borrow an immutable place", "receivers"),
    RejectCase("receivers/reject_immutable_receiver", "cannot call a mutating method on an immutable receiver", "receivers"),
    RejectCase("receivers/reject_receiver_argument_overlap", "overlapping arguments cannot include a mutable borrow", "receivers"),
    RejectCase("receivers/reject_pending_write_receiver", "cannot borrow an assignment destination while evaluating its right-hand side", "receivers"),
    RejectCase("receivers/reject_wrong_label", "argument label", "receivers"),
    RejectCase("receivers/reject_method_arity", "arguments", "receivers"),
    RejectCase("receivers/reject_method_type", "cannot implicitly convert", "receivers"),
    RejectCase("receivers/reject_temporary_receiver", "method calls require a named place receiver", "receivers"),
    RejectCase("receivers/reject_unknown_extension", "extension target must be a known record", "receivers"),
    RejectCase("receivers/reject_enum_extension", "extension target must be a known record", "receivers"),
    RejectCase("receivers/reject_trait_extension", "traits are not supported", "receivers"),
    RejectCase("receivers/reject_static_method", "static methods are not supported", "receivers"),
    RejectCase("receivers/reject_value_receiver", "methods require an explicit `&self` or `&var self` receiver", "receivers"),
    RejectCase("receivers/reject_duplicate_method", "duplicate method", "receivers"),
    RejectCase("receivers/reject_method_reference_result", "reference results are not supported", "receivers"),
    RejectCase("references/reject_alias_mutable_shared", "overlapping arguments cannot include a mutable borrow", "references"),
    RejectCase("references/reject_alias_two_fields", "overlapping arguments cannot include a mutable borrow", "references"),
    RejectCase("references/reject_later_read", "cannot read a place while it is mutably borrowed", "references"),
    RejectCase("references/reject_later_write", "cannot write a place while it is borrowed", "references"),
    RejectCase("references/reject_missing_ampersand", "reference argument requires explicit `&`", "references"),
    RejectCase("references/reject_missing_var", "mutable reference argument requires `&var`", "references"),
    RejectCase("references/reject_value_address", "value parameter does not accept an address argument", "references"),
    RejectCase("references/reject_wrong_referent", "reference argument type does not match parameter", "references"),
    RejectCase("references/reject_immutable_borrow", "cannot mutably borrow an immutable place", "references"),
    RejectCase("references/reject_shared_to_mutable", "cannot mutably borrow an immutable place", "references"),
    RejectCase("references/reject_mutate_shared", "cannot assign through a shared reference", "references"),
    RejectCase("references/reject_reference_local", "reference locals are not supported", "references"),
    RejectCase("references/reject_reference_field", "reference record fields are not supported", "references"),
    RejectCase("references/reject_reference_result", "reference results are not supported", "references"),
    RejectCase("references/reject_reference_static", "static type must be an integer or Bool", "references"),
    RejectCase("references/reject_nested_reference", "references to references are not supported", "references"),
    RejectCase("references/reject_outer_borrow_preserved", "cannot read a place while it is mutably borrowed", "references"),
    RejectCase("references/reject_spaced_nested_reference", "references to references are not supported", "references"),
    RejectCase("references/compound_lhs_snapshot", "cannot borrow an assignment destination while evaluating its right-hand side", "references"),
    RejectCase("references/reject_assignment_rhs_shared", "cannot borrow an assignment destination while evaluating its right-hand side", "references"),
    RejectCase("references/reject_assignment_rhs_mutable", "cannot borrow an assignment destination while evaluating its right-hand side", "references"),
    RejectCase("references/reject_compound_rhs_borrow", "cannot borrow an assignment destination while evaluating its right-hand side", "references"),
    RejectCase("references/reject_nested_assignment_rhs_borrow", "cannot borrow an assignment destination while evaluating its right-hand side", "references"),
    RejectCase("enums/reject_empty", "at least one case", "enums"),
    RejectCase("enums/reject_record_collision", "duplicate module name", "enums"),
    RejectCase("enums/reject_static_enum", "static type", "enums"),
    RejectCase("control/reject_static_negative_range", "integer literal", "control"),
    RejectCase("control/reject_static_typed_narrowing", "convert", "control"),
    RejectCase("control/reject_static_function_collision", "conflicts", "control"),
    RejectCase("records/reject_builtin_name", "reserved", "records"),
    RejectCase("records/reject_record_equality", "comparable type", "records"),
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
    RejectCase("reject_bool_arithmetic", "arithmetic requires integer operands"),
    RejectCase("reject_import", "only function, record, enum, static, and extension declarations are supported"),
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
    RejectCase("enums/reject_duplicate_enum", "duplicate module name", "enums"),
    RejectCase("enums/reject_duplicate_case", "duplicate enum case", "enums"),
    RejectCase("enums/reject_missing_match_case", "non-exhaustive match", "enums"),
    RejectCase("enums/reject_duplicate_arm", "duplicate match case", "enums"),
    RejectCase("enums/reject_arm_after_wildcard", "match arm follows wildcard", "enums"),
    RejectCase("enums/reject_wrong_qualifier", "does not match subject enum", "enums"),
    RejectCase("enums/reject_mixed_equality", "same type", "enums"),
    RejectCase("enums/reject_mixed_transfer", "cannot implicitly convert", "enums"),
    RejectCase("enums/reject_cast", "requires integer", "enums"),
    RejectCase("enums/reject_print", "cannot print an enum value", "enums"),
    RejectCase("enums/reject_payload", "payload enum cases are not supported", "enums"),
    RejectCase("enums/reject_arithmetic", "arithmetic requires integer operands", "enums"),
    RejectCase("values/reject_missing_else", "value if requires an else", "values"),
    RejectCase("values/reject_missing_tail", "continuing value branch requires a tail expression", "values"),
    RejectCase("values/reject_mismatched_branches", "control-flow branches have incompatible types", "values"),
    RejectCase("values/reject_unselected_range", "integer literal does not fit", "values"),
    RejectCase("values/reject_incomplete_match", "non-exhaustive match", "values"),
    RejectCase("values/reject_non_tail_expression", "only Void function calls may be expression statements", "values"),
    RejectCase("values/reject_arm_scope_leak", "unknown name", "values"),
    RejectCase("values/reject_record_branches", "incompatible types", "values"),
    RejectCase("values/reject_enum_branches", "incompatible types", "values"),
    RejectCase("values/reject_match_missing_tail", "continuing value branch requires a tail expression", "values"),
    RejectCase("values/reject_numeric_no_common", "incompatible types", "values"),
    RejectCase("values/reject_all_returning_operand", "all-returning control flow cannot be used as an operand", "values"),
    RejectCase("values/reject_deep_else_if", "nesting limit exceeded", "values"),
    RejectCase("values/reject_extra_call_argument", "too many arguments", "values"),
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


SAWC_KNOWN_DIVERGENCES = {
    # SL-260: the M8/M12 snapshot contract currently accepts a nested mutation
    # that Saw's receiver borrowing rules reject. Require this exact diagnostic;
    # disappearance or any different failure is a gate failure, not a silent skip.
    "unsigned_parse/receiver_snapshot": "exclusive access violation",
}


def test_sawc_case(python: str, sawc: Path, case: RunCase | RejectCase,
                   temp: Path) -> list[str]:
    """SL-260's first slice: identical sources, independent fixed oracles.

    Only explicitly marked shared-subset cases participate. Diagnostics differ
    between compilers, but rejection must be a normal diagnostic, never a crash.
    Known differences have an issue-linked, diagnostic-checked ledger below.
    """
    source = EXAMPLES / f"{case.name}.saw"
    output = temp / (case.name.replace("/", "-") + "-sawc")
    compiled = invoke([python, str(sawc), str(source), "-o", str(output)],
                      timeout=SAWC_COMPILE_TIMEOUT)
    known = SAWC_KNOWN_DIVERGENCES.get(case.name)
    if known is not None:
        diagnostic = (compiled.stdout + compiled.stderr).lower()
        plain = re.sub(r"\x1b\[[0-9;]*m", "", diagnostic)
        error_count = len(re.findall(r"^error:", plain, re.MULTILINE))
        if (compiled.returncode != 1 or known not in diagnostic
                or error_count != 1
                or "traceback" in diagnostic or "internal compiler error" in diagnostic):
            return [f"{case.name} sawc: SL-260 known divergence changed; "
                    f"exit {compiled.returncode}: {diagnostic!r}"]
        return []
    if isinstance(case, RejectCase):
        diagnostic = (compiled.stdout + compiled.stderr).lower()
        if (compiled.returncode != 1 or "error" not in diagnostic
                or "traceback" in diagnostic or "internal compiler error" in diagnostic):
            return [f"{case.name} sawc: expected diagnostic rejection, got "
                    f"exit {compiled.returncode}: {diagnostic!r}"]
        return []
    if compiled.returncode != 0:
        return [f"{case.name} sawc compile: exit {compiled.returncode}\n"
                f"stdout: {compiled.stdout}\nstderr: {compiled.stderr}"]
    return check_result(f"{case.name} sawc", invoke([str(output)]),
                        case.stdout, case.exit_code)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=Path(".build/minivm/minivm"))
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--sawc", type=Path,
                        help="also check explicitly marked shared-subset cases with this sawc.py")
    parser.add_argument("--sawc-python", default=sys.executable,
                        help="Python interpreter with sawc dependencies (default: this interpreter)")
    parser.add_argument(
        "--section", choices=("all", "core", "numbers", "records", "control", "enums", "values", "references", "receivers", "strings", "owning_records", "optionals", "results", "unsigned_parse"), default="all",
        help="run all cases or one isolated test section",
    )
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error(f"binary does not exist: {binary}")
    sawc = args.sawc.resolve() if args.sawc else None
    if sawc is not None and not sawc.is_file():
        parser.error(f"sawc does not exist: {sawc}")

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
        differential_cases = tuple(case for case in (*run_cases, *reject_cases)
                                   if case.compare_sawc) if sawc is not None else ()
        if sawc is not None and not differential_cases:
            parser.error("selected section has no declared sawc differential cases")
        for case in differential_cases:
            try:
                failures.extend(test_sawc_case(args.sawc_python, sawc, case, temp))
            except subprocess.TimeoutExpired as error:
                failures.append(f"{case.name} sawc: timed out after {error.timeout}s")
        limit_cases = () if args.section not in ("all", "core") else (
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
    if sawc is not None:
        known_count = sum(case.name in SAWC_KNOWN_DIVERGENCES for case in differential_cases)
        print(f"sawc differential: {len(differential_cases) - known_count} cases agree, "
              f"{known_count} known divergence(s) verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
