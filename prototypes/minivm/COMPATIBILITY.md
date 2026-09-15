# Prototype compatibility ledger

This is the index of known differences between the prototype and full Saw.
It is a work list, not a claim of language conformance. M1–M15 supply the
baseline; M16's lexer acceptance gate does not imply that the compiler can
compile itself or that every accepted program has production semantics.

The milestone documents are historical contracts: later milestones supersede
earlier exclusions (for example, M9 added String fields that M8 excluded).
Use this ledger and the current README for current scope. The language spec is
the target; Python sawc is a useful comparison oracle, not authority to copy a
known compiler bug.

## Ownership and access: semantic differences to remove

| Area | Current prototype | Required work toward full Saw | Evidence / owner |
| --- | --- | --- | --- |
| Vector element policy | Only non-Void, non-reference Copy elements; rejects nested vectors and other noncopyable elements. The vector itself is uniquely owned and NoCopy. | Admit noncopyable elements with correct move-in, scoped access, removal and destruction policies; do not simply remove the Copy check. | [M15](M15_VECTORS.md), `examples/vectors/reject_vector_element.saw`, `reject_noncopy_record_element.saw`; follow-up not yet scheduled. |
| Vector `[]` and `get` | Owned snapshots, including retained String leaves. No source-level pointer into storage escapes. `get` returns an Optional snapshot. | Implement production borrowing places: accessor `borrows`/`lend`, shared/exclusive use-site windows, root exclusivity, invalidation prevention and copy-tier checking for value reads. Scoped access must work for NoCopy elements. | [M15](M15_VECTORS.md), `examples/vectors/strings_records.saw`, `tests/vector_vm_contract.saw`; follow-up not yet scheduled. |
| Vector writes | No indexed assignment, element move-out or escaping element reference. | Define place writes and supported transfer operations with the same borrowing and ownership machinery. | [M15](M15_VECTORS.md); no general place implementation yet. |
| Whole-value transfers | Vector-bearing results and aggregate construction work; only whole direct local moves. Consuming Optional/Result matches and conditional bindings require fresh/temporary noncopyable subjects, not implicit reads of named wrappers. No vector-bearing by-value parameters, reassignment or value-if/match joins. | Generalize transfer decisions, aggregate moves, parameter/result ABI and replacement cleanup together. Handle moved fields and partial initialization before permitting partial moves. | [M15](M15_VECTORS.md), `examples/vectors/reject_move_field.saw`, `reject_value_parameter.saw`, `reject_assignment.saw`, `reject_value_control.saw`. |
| Move analysis | A move in any parsed branch invalidates the binding; moving an outer local inside a loop is refused. | Control-flow-aware move/initialization state at joins and loop back edges, with correct exit handling. | [M15](M15_VECTORS.md), `examples/vectors/reject_outer_loop_move.saw`. |
| Copy policy declarations | Only empty NoCopy markers on vector-bearing records; no arbitrary explicit policy or custom destructor. | Implement Copy/ExplicitCopy/NoCopy declaration rules, synthesis, user deinit and their propagation through fields and generics. | [M15](M15_VECTORS.md), `examples/vectors/reject_nocopy_copyable.saw`, `reject_nocopy_body.saw`. |
| Ordinary references | Direct-call shared/mutable references and forwarding; fields conservatively overlap by root. No stored/returned references or general reference expressions. | Extend place/provenance representation and escape rules; distinguish disjoint fields where Saw permits it. Preserve root exclusivity through lowering. | [M6](M6_SCALAR_REFERENCES.md), [M7](M7_RECORD_RECEIVERS.md), `examples/references/`, `examples/receivers/`. |
| String receiver evaluation | M17 registers a shared root borrow before intrinsic arguments, including named fields, references and parenthesized places. Fresh results do not retain source-place provenance. A staged receiver can read a pending assignment destination (`text = text.substring(...)`); arguments still cannot borrow that destination or mutate the active receiver. | Generalize the conservative record-root checks with the ordinary place machinery. | [M17](M17_SHARED_SUBSET.md), `examples/strings/receiver_borrow_controls.saw`, `receiver_self_assignment.saw`; the old M8/M12 overlapping-mutation cases are now rejection tests. |
| StringBuilder ownership | Local builders and references only; no moves into aggregates, by-value parameters/results or reassignment. | Generalize builder ownership using the same transfer machinery as other noncopyable values. | [M14](M14_STRING_BUILDER.md), `examples/builders/`. |
| Lexical shadowing | Broader shadowing accepted than Saw's design-100 rule. | Enforce the production binding/shadowing rules with positive and negative scope tests. | SL-289, [M3](M3_SCALAR_CONTROL.md), `examples/scopes.saw` and `shadow_initializer.saw`; the differential manifest tracks the unrelated shadow as a known difference. |

## Syntax, type system and standard surface

| Area | Current boundary | Required extension | Evidence / owner |
| --- | --- | --- | --- |
| Modules and visibility | Single-file input. `public` syntax is accepted without full API visibility checks. The prototype's small builtin namespace also permits names such as Box that collide with production prelude declarations. | Module loading, namespaces/import forms, identity and visibility checks, extension/conformance lookup and the complete prelude surface. | README, [M7](M7_RECORD_RECEIVERS.md); `examples/optionals/token_tok_extract.saw` exposes a public field naming a private enum, and `examples/records/one_word_result.saw` declares Box. SL-259 concatenates an unchanged import-free lexer with a driver. |
| Generics and traits | Compiler-known Optional/Result/Vector applications and intrinsic overloads; no general generic declarations or trait system. | Generic AST/type representation, parameter binding, constraints, inference, specialization, trait dispatch and synthesis; do not confuse builtin descriptors with generic support. | [M10](M10_OPTIONALS.md), [M11](M11_RESULTS.md), [M15](M15_VECTORS.md). |
| Recursive data and AST | Finite flattened value layouts; rejects direct/indirect by-value cycles. M18's separate syntax parser stores recursive syntax through arena indices; this compiler still lowers directly from tokens and has no recursive heap representation. | Expand the standalone parser, add canonical AST comparison, then separate semantic/lowering phases; later add indirect recursive storage and ownership. By-value cycles must remain invalid. | [M2](M2_RECORDS.md), `src/model.saw`, [M18](M18_AST.md), [parser boundaries](../parser/README.md); SL-300/301. |
| Records and declarations | Named field construction; no user initializers, general static methods or overload declarations. | Declaration resolution, initializer semantics, overload selection and supported extension forms. | [M2](M2_RECORDS.md), [M7](M7_RECORD_RECEIVERS.md), `examples/receivers/`. |
| Enums and patterns | Nonempty payload-free user enums plus builtin Optional/Result payloads; bounded exhaustive matching. The prototype accepts qualified `case Switch.Off` patterns; full Saw requires a bare variant pattern. | Reconcile pattern syntax, then add general payload enums, recursive patterns, empty enums, raw-value enum surface and enum extensions. | [M4](M4_ENUMS.md), `examples/enums/match_qualified.saw`, [M10](M10_OPTIONALS.md), [M11](M11_RESULTS.md). |
| Control flow | Conditional while, if/match and returns; M16 adds bare statement break. No for/continue, loop values, general Never, closures or function values. | Structured control-flow outcomes, bottom typing and loop result types; closures/captures and callable representations. | [M5](M5_VALUE_CONTROL.md), [M16](M16_LEXER_ACCEPTANCE.md); SL-259 owns only bare break. |
| Value inference | Bounded literal adoption and value-branch inference; all-returning nested operands may be refused. M5 deliberately lets a bare literal adopt a typed sibling in an unannotated value-if, e.g. `if flag { 5 } else { 6u8 }`; production infers Int and rejects the later UInt8 argument. | Reconcile literal inference with the language rules and current production behavior; general expected-type propagation and divergence typing must preserve ownership on every edge. | [M1](M1_NUMBERS.md), [M5](M5_VALUE_CONTROL.md); `examples/values/contexts.saw` and `inference_order_widening.saw` are explicit whole-fixture differential exclusions because of these sibling-literal cases. Their other arithmetic remains covered by the ordinary regression gate. |
| Discarded expressions | Ordinary expression statements and M16 statement-match expression arms admit only Void calls. Explicit `_` discards are separate. | Generalize permitted discarded expressions according to Saw's rules while retaining the prohibition on implicitly discarded Result values. | [M5](M5_VALUE_CONTROL.md), [M16](M16_LEXER_ACCEPTANCE.md), `src/frontend.saw`. |
| Bare braces in statement position | The prototype executes `{ ... }` as a lexical block. Production Saw parses it as a closure literal and rejects an uncalled discarded closure. | Reconcile this syntax when implementing closures; remove the executable-bare-block shortcut. Shared-subset drivers use `if true { ... }` or functions for a scope. | `parse_statement` in `src/frontend.saw`; exposed by the M16 differential driver. The M17 fixture audit found no remaining registered example with this statement form. |
| Optional operations | Contextual None/wrapping and conditional binding; no `??`, `?.` or postfix force unwrap. M10 recursively wraps payloads at expected Optional destinations, including an Optional argument into another layer. Full Saw's call-site rule permits only a bare nonoptional value's one-level wrap. | Reconcile wrapping depth at each transfer position; add remaining operators with short-circuiting, copy/move policy and cleanup. | [M10](M10_OPTIONALS.md), `examples/optionals/review_nested_context.saw`; SL-290 tracks Python's internal error on the nested argument rather than the clean rejection its call-site rule requires. |
| Errors | Fixed Result, try and try!; no catch/try? or general Error machinery. Forced failure uses a fixed message. Void success matches use bare `case Ok`; production requires an associated-value pattern such as `case Ok(_)`. | Error conformance, formatting and remaining handling forms, preserving transfers and cleanup; reconcile Void pattern syntax. | [M11](M11_RESULTS.md), `examples/results/void_success.saw`, `try_void.saw` and `examples/builders/result_alloc_error.saw`. |
| Numeric and type surface | Fixed-width integers/Bool/Byte and a subset of conversions; no source floating-point arithmetic, general aliases, tuples or arrays. M1 conflates Int with Int64 and UInt with UInt64 and permits lossless transfers between distinct fixed widths. Production requires a platform type on at least one side of an implicit widening. | Preserve platform/fixed-width source type identity separately from representation, reconcile widening rules, and add remaining types/conversions with independent boundary oracles. | [M1](M1_NUMBERS.md), [M12](M12_UNSIGNED_PARSE.md); `examples/numbers/lossless_widening.saw` and `examples/control/static_literals.saw` expose the broader prototype conversions. |
| Static storage | Module integer/Bool constants with restricted initializers; no dynamic or owning statics. | Constant evaluation and static lifetime/initialization rules for additional types. | [M3](M3_SCALAR_CONTROL.md). |
| Strings and formatting | Owned String operations, but no source interpolation, concatenation, general Printable or format-print API. | Lower interpolation and formatting with specified allocation/evaluation behavior. Lexing interpolation tokens is not compiling interpolation expressions. | [M8](M8_OWNED_STRINGS.md), [M9](M9_OWNING_RECORDS_MATCH.md), `examples/strings/`. |
| Scalar errors | Checked Scalar construction/readout; InvalidScalar is opaque rather than the full production error surface. | Expose its specified cases and formatting with nominal identity preserved. | [M13](M13_SCALAR.md), `examples/scalars/`. |
| Library breadth | Intrinsics for a narrow String/Builder/Vector subset; no general collections, allocators, files/network or other stdlib modules. | General language/FFI/runtime support, then compile or deliberately implement each library contract. | [LEXER_DEPENDENCIES](LEXER_DEPENDENCIES.md); SL-259 adds Builder.clear only. |
| Coroutines and concurrency | No tasks, suspension, spawning, channels, threads, effects or Send/Sync. | Coroutine/state-machine lowering, frame ownership and cancellation, scheduler/runtime, effects and concurrency safety. | Outside lexer acceptance; requires its own design and interaction tests. |
| Unsafe and platform integration | No general unsafe surface, pointers, FFI or freestanding runtime authoring. | Specify representation/ABI and checker rules before adding these capabilities. | Outside the current prototype subset. |

## Implementation limits, not intended language rules

| Limit | Current behavior | Follow-up |
| --- | --- | --- |
| Aggregate layout | At most 256 words and 128 nesting levels. | Revisit representation and resource limits as real workloads require; retain explicit exhaustion diagnostics. |
| VM execution | Default 1,000,000 instructions and 128 call frames; budget configurable. | Keep resource controls distinct from language semantics; size acceptance budgets explicitly. |
| Compiler resources | Bounded nesting, linear lookup, direct parse-to-instruction lowering. | Arena AST, indexed lookup and separated semantic/lowering passes; profile before optimizing. |
| Vector growth | Native push reallocates exact storage; VM stages storage. Correctness-first, potentially quadratic growth. | Capacity strategy with equivalent failure/ownership behavior and measured tests. |
| Allocation error sizes | Builder append reports exact replacement size (`new_len + 16`); Vector push reports exact new element-buffer bytes. Production capacity growth may request different sizes. | Treat allocation strategy and reported requested size together; do not claim byte-for-byte error-size parity with production collection growth. |
| Allocation behavior | Recoverable Builder append/Vector push failure tested; infrastructure allocation and constructor boundaries can still trap. M16 Builder.clear replaces the backing String with a newly allocated empty header in both engines; it does not consume the append-failure counter. | Audit every hidden allocation against Saw's allocation policy before claiming parity, including a nonallocating clear representation. |
| Native target | Textual LLVM for a 64-bit Unix C ABI, validated with arm64 macOS clang. | Explicit target/ABI/runtime portability tests; no cross-target claim from host-only validation. |
| IR verifier | Structural/type validation; frontend establishes initialization and ownership. | Stronger dataflow verification if IR is ever loaded from an untrusted producer. |
| Diagnostics | Prototype-specific errors and fixed runtime trap text. | Diagnostic and runtime reporting parity is separate from successful-program behavior. |

## Production findings are not compatibility requirements

SL-284 records an implicit receiver-borrow overlap accepted by Python sawc;
SL-285 records incorrect labels accepted on named borrowing accessors. The
prototype rejects those calls. Shared-subset comparison deliberately excludes
those incorrect production acceptances. Check current tracker status before
changing exclusions: fixing Python does not require weakening the prototype.

M17's expanded comparison also found SL-291 (Result payload assignment does not
wrap at local/reference destinations) and SL-292 (an annotated Result value-if
loses its destination context). The prototype keeps its correct wrapping behavior;
these are issue-linked known production over-rejections. SL-290 is recorded as a
known internal compiler error, distinct from a clean rejection. Its call-site
reproducer also uses M10's broader Optional-wrapping extension described above.

The same audit filed SL-294 (later argument reads/writes bypass whole-call borrow
checks), SL-295 (dead statements poison an unconditional return's result),
SL-296 (missing Result type argument reaches codegen with unbound E), SL-297
(duplicate constructor labels), SL-298 (reachable missing-return path accepted)
and SL-299 (out-of-range uncontextualized Int silently truncates). Each is tracked
by its exact fixture and expected production outcome in the differential manifest;
the prototype retains its correct behavior. SL-296 is a separately reported known
internal error, rather than a language rejection.

## Keeping this ledger useful

Every new milestone updates affected rows, names the tests that establish its
new boundary, and removes superseded exclusions. New differences found by
whole-lexer or parser work get a row and a focused reproducer; production bugs
also go to sawtracker. Rows without a scheduled issue remain explicit backlog,
not silently completed work.

This initial ledger consolidates the milestone contracts and known divergence
tests. A full specification-to-implementation conformance audit remains owed;
absence of a feature from this list is not evidence that it works.
