# The frozen-parser comparison

SL-424's contract, item 9: the self-hosted parser was compared once with the
frozen parser in `sawc/parser/` over the part of the language that did not
change, and the result is recorded here. After this check only the fixtures of
`compiler/tests/parse/` count, so it is not a lane: nothing in
`compiler/tests/run.py` runs it. `compiler/tools/frozen_compare.py` is the
script, and it stays runnable.

## Method

**The files.** The unchanged part of the language is:

- every file of `tests/corpus/` that `MIGRATION.tsv` marks `copied` or
  `reviewed`, whatever else its status says, and whose text is byte for byte
  the `examples/` file of the same path;
- every tracked `.saw` file of `sawc/std/`, `blade/` and `libs/`.

**The verdicts.** The script calls the frozen lexer and parser through their
Python API (`Lexer(source).tokenize()`, then `Parser(...).parse()`), so a file
is refused only when it fails to lex or parse. It does not use
`sawc.py --emit-ast`, which dumps the typed tree and would count a file that
fails to typecheck as refused. A `SyntaxError` is a refusal, and any other
exception would be counted apart as a crash. sawc2 runs once, as
`sawc2 parse --dump`, over the whole list.

**The shape.** Where both parsers accept a file, the script compares a shape
both trees hold, not the whole tree:

- every item of the file, and of each inline module's body: its kind, its name
  and its order;
- every function, meaning a top-level `func`, an extension's method or `init`,
  and a trait requirement: its name, its parameters less the receiver, and the
  number of statements in its body, a trailing expression counted as one.

A table in the script, `KINDS`, maps the frozen parser's `Program` list an item
lands in to the node GRAMMAR.md builds for it:

| frozen `Program` list | kind | GRAMMAR.md node | name compared |
|---|---|---|---|
| `functions` | func | `Func` | the name |
| `structs` | struct | `Struct` | the name |
| `enums` | enum | `Enum` | the name |
| `traits` | trait | `Trait` | the name |
| `extensions` | extension | `Extension` | the extended path |
| `type_definitions` | type-alias | `TypeAlias` | the name |
| `extern_blocks` | extern | `ExternBlock` | none |
| `statics` | static | `Static` | the name |
| `imports` | import | `Import` | the module path |
| `module_decls` | module | `ModuleDecl` | the name |
| `static_asserts` | static_assert | `StaticAssert` | none |
| `exports` | export | none: GRAMMAR.md refuses `export` | none |

The frozen parser files each item under a list by kind, so the order comes from
a subclass that notes which list grows at each top-level declaration. The
frozen parser keeps a receiver as a parameter named `self`, and GRAMMAR.md as a
`Param.receiver`; neither is counted. The first run found two slips in the
mapping, which the table and the name reading now handle: a receiver counted
on one side only, and an effect word read as a method's name. Once they were
fixed, nothing else differed.

The mapping does not cover statements' contents, expressions, types, patterns,
struct fields, enum cases, attributes or docs. The parser corpus covers those
against GRAMMAR.md.

## Counts

| | files |
|---|---|
| compared | 2,704 |
| `tests/corpus/` | 2,622 |
| `sawc/std/` | 33 |
| `blade/` | 36 |
| `libs/` | 13 |
| marked files whose text differs from `examples/` | 0 |
| accepted by both, same shape | 2,589 |
| accepted by both, shape differs | 0 |
| refused by both | 85 |
| accepted by the frozen parser only | 3 |
| accepted by sawc2 only | 27 |

Where both accept, the shape covered 12,660 items and 9,305 functions. The
frozen parser crashed on no file.

## Disagreements

Every disagreement is in the verdict, and each is one of these kinds:

- (a) a ruled grammar change, with its GRAMMAR.md §16 row or ruling;
- (b) a frozen-parser defect, with its §16 `defect` row;
- (c) a sawc2 bug.

There are 29 of kind (a), 1 of kind (b) and none of kind (c).

### (a) Ruled grammar changes

**References outside a parameter: 21 files, accepted by sawc2 only.** The
§16 row is syntax.type.ref (`later`, Reference passing; SL:borrowing §2.6). The
grammar parses `&T` wherever a type goes, and a later stage refuses it. The
frozen parser refuses the reference type while parsing, with "... may not
return a reference" or "a generic argument may not be a reference".

- `tests/corpus/conformance/R07_return_optional_ref.saw`, at 10:20
- `tests/corpus/conformance/R08_return_vector_of_ref.saw`, at 9:20
- `tests/corpus/conformance/R18_map_value_ref.saw`, at 9:21
- `tests/corpus/conformance/R26_optional_written_name_ref.saw`, at 9:20
- `tests/corpus/conformance/R27_nested_generic_ref.saw`, at 7:22
- `tests/corpus/conformance/R32_box_of_ref.saw`, at 10:17
- `tests/corpus/conformance/R33_borrows_lends_ref_type.saw`, at 24:26
- `tests/corpus/conformance/R34_field_of_ref_returning_fn_type.saw`, at 8:29
- `tests/corpus/enum_ref_payload_escape.saw`, at 13:18
- `tests/corpus/errors/ref_field_nested_in_tuple.saw`, at 12:21
- `tests/corpus/errors/ref_field_type.saw`, at 12:20
- `tests/corpus/errors/ref_return_dangles.saw`, at 14:18
- `tests/corpus/errors/ref_return_extern.saw`, at 11:30
- `tests/corpus/errors/ref_return_function_type.saw`, at 12:29
- `tests/corpus/errors/ref_return_method.saw`, at 18:25
- `tests/corpus/errors/ref_return_nested_in_tuple.saw`, at 12:16
- `tests/corpus/errors/ref_return_suspending_anchored.saw`, at 15:23
- `tests/corpus/errors/ref_return_trait_method.saw`, at 11:28
- `tests/corpus/errors/ref_return_var_flavor.saw`, at 10:27
- `tests/corpus/errors/ref_type_arg_generic_func.saw`, at 17:17
- `tests/corpus/errors/ref_type_arg_generic_struct.saw`, at 13:19

**Other files accepted by sawc2 only, 5:**

| file | frozen refusal | §16 row |
|---|---|---|
| `tests/corpus/errors/borrowing_struct_exclusive_field.saw` | 24:18, a `&var` field in a `borrows struct` | syntax.decl.struct-modifier.borrows (`ruled`, SL:borrowing §2.6) |
| `tests/corpus/errors/borrows_function_type_rejected.saw` | 10:21, `borrows` in a function type | syntax.decl.borrows-sync, syntax.type.func-borrows (`ruled`, SL:borrowing §2.5) |
| `tests/corpus/errors/borrows_trait_requirement_rejected.saw` | 10:40, `borrows` on a trait requirement | syntax.rule.requirement-borrows (`ruled`, SL:borrowing §5.4) |
| `tests/corpus/errors/consumes_beside_borrows.saw` | 15:49, `consumes` beside `borrows` | syntax.rule.effect-slot (`later`, Consuming method receivers) |
| `tests/corpus/errors/subscript_must_be_borrows.saw` | 12:35, a `[]` subscript without `borrows` | syntax.decl.setitem-name, syntax.rule.subscript-declaration (`ruled`, SL:borrowing §5.1) |

**Accepted by the frozen parser only, 3:**

| file | sawc2 refusal | §16 row |
|---|---|---|
| `tests/corpus/export_outside_init_error.saw` | syntax.decl.refused-export at 5:1 | syntax.decl.refused-export (`ruled`, SL-400 c6); marked `grammar-flip` |
| `tests/corpus/try_routing_clause_refusals.saw` | syntax.expr.refused-try-route at 63:9 | syntax.expr.refused-try-route (`earlier`, Error routing at `try`); marked `grammar-flip` |
| `sawc/std/data.saw` | syntax.expr.refused-lend-var at 189:12, `if #lend_var` | syntax.expr.refused-lend-var (`ruled`, SL:borrowing §4); std is written in the frozen language until the bootstrap std replaces it |

Of these 29 files, the 28 in `tests/corpus/` are exactly the files that
`MIGRATION.tsv` marks `grammar-flip`: error tests whose parse outcome a ruling
changed.

### (b) Frozen-parser defects

| file | frozen refusal | §16 row |
|---|---|---|
| `tests/corpus/trailing_closure_inside_a_try_operand.saw` | 47:32, "two statements on one line need a `;` between them", at the `{` of `try! jobs.map { j in j.label() }` | syntax.expr.try, syntax.rule.trailing-closure (`defect`, Try Variants; DF-259c), added by this check |

The file is the XFAIL pin of DF-259c in `examples/`, where the frozen parser
reads no trailing closure inside a `try` operand. GRAMMAR.md attaches one
there as anywhere else, and sawc2 parses the file with `map` taking the
closure. LANGUAGE_SPEC.md's `Vector.each` section notes the same defect.

### (c) sawc2 bugs

None.
