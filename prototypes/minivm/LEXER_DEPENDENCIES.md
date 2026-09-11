# Lexer dependency inventory

Scope: the source to admit is `selfhost/lexer/src/lib.saw` (1,215 lines at the
`5af086c4` baseline). This inventory is intentionally narrower than general Saw
support. A feature is included only when that file uses it, or when it is an
unavoidable implementation dependency of one of the public std operations it
calls. This inventory was taken at the 43-case Int32/Bool baseline. M1 now supplies
the numeric foundation; M2 supplies scalar value records, and M3 adds module
constants, compound assignment and short-circuit Booleans. M4 supplies payload-free
enums and exhaustive statement match, including the actual TokenKind declaration
in isolation. M5 adds implicit tails, value if/match and else-if chains, including
the unchanged numeric `hex_value` helper (193 total cases).
M6 supplies direct-call scalar references, forwarding and mutation, including
borrowing scalar fields of direct records. M7 adds whole-record references,
nested field forwarding and basic shared/mutable methods, tested with a
scalar-only `Lexer.advance`-shaped record (250 total cases). M8 adds owned String literals/locals/parameters/results/references,
byte length/access, equality and substring with explicit copy/drop rules (277
total cases). M9 adds String-valued records and String-pattern match (288 cases),
including unchanged keyword/suffix classification and the actual String-backed
Lexer.advance. M10 adds Optional payloads, contextual None/wrapping and value
conditional binding, including the unchanged Token/tok extraction (307 cases).
M11 adds fixed `Result<T,E>` construction and matching plus `try`/`try!`
propagation, including owning payloads and Void success (336 cases). Next are
checked unsigned parsing, `Scalar`, `StringBuilder`, and `Vector`. The lexer has
no imports, so its first whole-file test can combine the unchanged library with
a small wrapper without implementing general module loading.
The dependency groups below are an inventory, not the implementation commit order;
the numbered milestone designs define each isolated slice.

## Exact source surface used by the lexer

### Declarations, names, and construction

- Module-scope typed constants: the `static B_*: Int = ...` declarations at
  `lib.saw:17-76`. They require `Int`, including negative literals/values, rather
  than the prototype's source-only `Int32`. Constants are referenced from any
  function and must be initialized as compile-time scalar constants; mutable or
  dynamically initialized statics are not needed.
- Payload-free public enum `TokenKind` at `lib.saw:133-235`, with qualified case
  names (`TokenKind.IntLit`) and unqualified cases in `match`. Equality and
  inequality on this enum are required (`lib.saw:985` and elsewhere). Numeric
  discriminants, payload cases, raw-value APIs, and user-defined enum layout are
  not required by this lexer.
- Public field structs `Token`, `LexError`, `DocComment`, and `LexResult` at
  `lib.saw:242-279`, plus private `Lexer` at `lib.saw:559-565`. Construction uses
  order-independent named fields, field reads, and mutable field assignment
  through `&var self` (`advance`, `lib.saw:576-586`). Visibility must parse and
  type-check; cross-module consumers need the four public models and their public
  fields. Private fields and custom initializers are unnecessary here.
- `extension LexResult: NoCopy {}` (`lib.saw:279`) and `extension Lexer { ... }`
  (`lib.saw:567-1189`). The former must suppress implicit copying; the latter
  supplies instance methods with `&self` and `&var self` receivers. Traits in
  general and extension dispatch across arbitrary types are outside this slice.
- Public and private free functions, expression-bodied functions, implicit tail
  returns, explicit `return`, and named arguments (all struct construction and
  `Scalar(value: cp)` at `lib.saw:699`). Default arguments, closures, overload
  declarations in user code, and function values are unused.

### Types, operators, and conversions

- Primitive types: `Int`, `Bool`, `String`, `Void`, `Byte`, `UInt`, `UInt8`,
  `UInt16`, and `UInt32`. Only `Int` arithmetic is performed by lexer code:
  checked `+ - * / %`, comparisons, and assignment forms `+=`/`-=`
  (`lib.saw:576-586`, `985`, `1104-1117`). `UInt` only receives `String.to_uint`
  results and participates in `<=`; fixed unsigned types are used for their
  `max` constants and casts. No source floating-point arithmetic is needed even
  though the lexer emits `FloatLit` tokens.
- Static primitive constants `UInt8.max`, `UInt16.max`, and `UInt32.max`, then
  widening casts `as UInt` (`literal_fits`, `lib.saw:539-553`). `UInt.max` and
  `Int.max` are not directly used by this source.
- Checked widening `s.byte_at(i) as Int` (`lib.saw:89`) and constructor/cast chain
  `Byte(UInt8.from(truncating: u))` (`lib.saw:95-97`). This requires static method
  lookup on a primitive and the intrinsic low-bit conversion behavior of
  `UInt8.from(truncating:)`. It does not require compiling all of `std.numeric`.
- Boolean `not`, `&&`, and `||`, with short-circuit evaluation (for example
  `lib.saw:602-604`, `626-637`, and `967-1175`). Parenthesized expressions and
  precedence must cover these alongside comparisons and arithmetic.
- String literals including escape sequences used in diagnostics, but the
  compiler need not implement interpolation to compile this file: apparent
  braces in its diagnostic strings are escaped. Runtime string equality is used
  both by `==` in `keyword_kind`'s string `match` and explicitly by
  `name_str.equals(...)` at `lib.saw:931-932`.

### Ownership, references, generics, and fallibility

- Shared references `&T`, mutable references `&var T`, address-taking `&expr` /
  `&var place`, and receiver exclusivity. Required examples include `ubyte(&s,
  i)`, `read_unicode_escape(&var self, out: &var StringBuilder)`, and passing
  `&var docs` through `tokenize`. References need load/store and lifetime safety
  sufficient for direct calls; reference fields, returned references, pointer
  arithmetic, and unsafe user pointers are not used by lexer source.
- Copy versus move behavior must distinguish scalar/Copy values (`Int`, `Bool`,
  `String`, payload-free `TokenKind`, `Byte`, unsigned integers) from aggregate
  ownership. `LexResult` is explicitly `NoCopy`; its two vectors are moved into
  the result at `lib.saw:1210-1215`. Vector elements include owning `String` and
  `String?`, so pushing/returning structs must retain/move/drop exactly once.
  The lexer explicitly moves both vectors into `LexResult` at `lib.saw:1215`;
  other transfers and copies must follow each payload's copy policy.
- Generic type application is needed for `Vector<Token>`, `Vector<DocComment>`,
  `Result<T, LexError>`, and `String?`. The lexer declares no generic function or
  type itself. A monomorphized built-in/runtime implementation is sufficient;
  generic declaration parsing, bounds, defaults, and arbitrary specialization
  are needed only if the mini-VM chooses to compile the std source rather than
  expose these few APIs intrinsically.
- Optional construction/patterns: `None`, implicit wrapping of a bare `String`
  on the success tail of `try_read_int_suffix`, and `if let name = optional`
  (`lib.saw:476`, `540`, `787-817`, `857`, `904`). Optional payload moves must be
  correct for `String`.
- `Result<T,E>`, `try expr`, and `try! expr`. `try` propagates `LexError` from
  lexer helpers (`lib.saw:739`, `967-1177`, `1210-1215`); `try!` unwraps
  allocation results from builders/vectors and `Scalar(value:)`. Only `Ok`/`Err`
  representation, success extraction, error propagation, and trap-on-error are
  needed. `catch`, `try?`, and general `Error` conformance are unused.

### Control flow and syntax sugar

- `if`/`else if` statements, value-producing `if` expressions (`lib.saw:650,
  780, 845-846`), `while`, and early `return`. `for`, `break`, `continue`, and
  `guard` do not occur in this lexer.
- Exhaustive `match` over strings with literal cases and `_`
  (`keyword_kind`, `lib.saw:289-326`), and over payload-free enum values with
  both qualified and unqualified case patterns (`kind_name`, `lib.saw:330-438`).
  Guards, payload destructuring, nested patterns, and non-string scalar matches
  are unnecessary.
- Local inference, shadowing, `_` discard bindings, and compound assignment.
  The postfix/member grammar must distinguish method calls, field access, and
  static enum/type members. Vector subscripting is required for token lookback.
  Array literals, tuples, ranges, and interpolation syntax are not used to
  implement the lexer itself.

## Minimal std/runtime contract

These are the only public behaviors the lexer calls. Their current production
definitions are useful specifications, not a requirement that the mini-VM first
compile their full implementations.

- `String.len(&self) -> Int` (`sawc/std/string.saw:53`): UTF-8 byte length,
  including embedded NUL. `String.byte_at(&self, index: Int) -> Byte`
  (`:75`): unsigned byte, bounds checked. `substring(&self, start: Int, end: Int)
  -> String` (`:426`): copied half-open byte range, bounds checked. `is_empty()`
  is used at `lib.saw:855,927` and can be intrinsic or derived from `len == 0`.
  `equals(&self, other: String) -> Bool` (`:360`) and `==` need byte-content
  equality. `to_uint(&self, radix: Int) -> UInt?` (`:677`) must accept bases
  2/8/10/16 and return `None` on invalid digits or overflow past 64 bits. The
  lexer does not need trimming, Unicode iteration, replacement, joins, hashing,
  or general formatting from `std.string`.
- `StringBuilder()` (`sawc/std/stringbuilder.saw:58`),
  `append(&var self, String)` (`:146`), `append(..., Int)` (`:191`),
  `append(..., Byte)` (`:254`), `append(..., Scalar)` (`:348`), and
  `build(&self) -> String` (`:414`). Appends preserve raw bytes; integer append
  is decimal; scalar append is valid UTF-8; build returns independent string
  contents and may leave the builder reusable. All append overloads return
  `Result<Void, AllocError>`, but lexer paths deliberately use `try!`. Capacity,
  fixed mode, allocator traits, `UnsafeSend`/`UnsafeSync`, raw pointers, memcpy,
  and growth algorithms in the std implementation are transitive implementation
  details and should not become source-language prerequisites.
- `Vector<T>()`, `len(&self) -> Int`, indexed shared read, and
  `push(&var self, value: T) -> Result<Void, AllocError>` are used throughout;
  production declarations are `sawc/std/vector.saw:43,67,93,231`. Required
  instantiations are `Vector<Token>` and `Vector<DocComment>`. Bounds-checked
  indexing appears only for token lookback (`lib.saw:985`). `pop`, iteration,
  reserve, copy, custom allocators, and mutable indexing are unused by this
  lexer. The std type's allocator parameter/default and pointer implementation
  are therefore avoidable if the mini-VM provides an opaque monomorphic vector.
- `Scalar(value: Int) -> Result<Scalar, InvalidScalar>`
  (`sawc/std/scalar.saw:64,85`) and builder append encode one already-validated
  scalar. The lexer independently rejects out-of-range and surrogate code points
  before construction. Payload enum `InvalidScalar`, Printable/Error traits, and
  the rest of `std.scalar` are transitive if construction is intrinsic.
- `Byte`, `UInt*`, `String`, `Optional`, `Result`, `AllocError`, and `NoCopy` are
  prelude-visible in the production compiler. For this prototype they may be
  compiler-known types. Reproducing their complete std declarations would pull
  in allocators, unsafe pointers, traits, synthesis, deinitializers, and FFI that
  the lexer never exercises.

## Dependency order and isolated gates

Each gate should add a tiny source fixture and assert both VM behavior and a
precise rejection. Keep all earlier milestone tests green at every gate.

1. **Wide scalar foundation.** Add source `Int`, unsigned fixed-width values,
   `Byte`, the listed operators/casts, `from(truncating:)`, and `.max`. Test
   `Int` values beyond `Int32`, byte 255 round-trip, the three maxima widened to
   `UInt`, signed `-1`, short-circuit suppression of a trapping RHS (a subsequent frontend slice), and reject
   unsupported casts/overflow.
2. **Strings and static constants.** Add module `static Int` constants, owned
   strings, literals, equality, `len`, `byte_at`, `substring`, `is_empty`, and
   `to_uint(radix)`. Test embedded NUL/non-ASCII byte length, unsigned bytes,
   valid/invalid bounds, radix parsing at `UInt.max`, and overflow to `None`.
3. **Structs, enums, and methods.** Add named-field structs, payload-free enums,
   equality, qualified members, extensions, `&self`/`&var self`, field mutation,
   and named calls. Test an `advance`-shaped mutable receiver and reject mutation
   through `&self`, wrong labels, missing fields, and non-exhaustive enum match.
4. **Optional/Result control flow — complete through M11.** `T?`, fixed
   `Result<T,E>`, `None`, implicit injection, `if let`, `try`, and `try!` are
   covered with owning String payloads, propagation, and trap behavior.
5. **Opaque builder and vector generics.** Expose only the contracts listed
   above and implement correct ownership for `Vector<Token>` /
   `Vector<DocComment>`. Test growth, indexing bounds, push of structs containing
   `String?`, builder overload selection, build independence, and Unicode scalar
   UTF-8 output. Reject unsupported generic types/operations explicitly.
6. **Lexer syntax completion.** Add string and enum `match`, if-expressions,
   public declarations, `NoCopy`, compound assignments, tail expressions, and
   `_` discards. Compile focused extracts of `keyword_kind`, `kind_name`,
   `literal_fits`, and `Lexer.advance`; compare their outputs to hand-written
   oracles.
7. **Whole-module compile and differential lexing.** Compile the unchanged
   `selfhost/lexer/src/lib.saw`, call `lex` and `lex_all`, and compare canonical
   token/error/doc records against the production lexer. Minimum cases: every
   keyword/operator, comments/docs, decimal/base/float/suffix boundaries,
   escaped and interpolated strings, Unicode scalar edges, raw multi-byte UTF-8
   columns, EOF, and each error path. This gate is where ownership/leak checks
   for repeated lexing matter; agreement between two engines still needs fixed
   expected records for representative cases.

## Outstanding design choices to settle before implementation

- Numeric representation is settled in M1_NUMBERS.md: 64-bit bit-pattern cells,
  with signed/unsigned interpretation carried by slot types. `UInt` must retain
  all 64 bits from `to_uint`; treating those cells as signed mathematical values
  during comparisons, casts, arithmetic, or printing would be incorrect.
- Decide whether String/Builder/Vector are opaque runtime handles or lowered
  native aggregates. Opaque handles keep allocator, unsafe-pointer, FFI, trait,
  and generic-stdlib implementation out of the prerequisite chain and are the
  smallest lexer-specific route.
- Define retain/move/drop points before vectors of `Token` are enabled. The
  observable lexer contract does not expose refcounts, but stale/double-freed
  `String` and `String?` payloads will otherwise make differential results
  nondeterministic.
- Define how `try!` failure is surfaced by the mini-VM and emitted LLVM. Lexer
  allocation failures are allowed to trap, but the two backends need one tested
  behavior.
- Keep unsupported production language features as located rejections. Compiling
  the complete production std files is not a milestone requirement and would
  silently expand this project into traits, allocators, unsafe pointers, FFI,
  synthesis, and deinitialization before the lexer can run.
