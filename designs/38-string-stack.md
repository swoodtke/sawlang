# Design Brief 38 — String stack: API expansion, UTF-8 validation, StringBuilder

**Source:** tracker S1/S2/S3 (papers 07/11 deferred these when the
refcounted representation landed). Builds on: brief 11 (the refcounted
immutable String), brief 29 (non-escaping closures — `withCString`'s
enabling feature), brief 28/37 (Global allocation), design 30/32
(Result + Equatable patterns to follow).
**Out of scope:** SSO (S5, ABI-gated, stays deferred); ordering
comparisons / a Comparable trait (needs its own decision — note it,
don't build it); a `Char` primitive type (spec lists it; not built —
`chars()` yields Int scalar values for now, documented).
**Exit criteria:** each item lands with tests; full suite green;
exactly the 2 sanctioned ledger xfails.

## Items

### 1. `String.fromBytes` (S1) + runtime UTF-8 validation (S2 half)
`String.fromBytes(data: &Data) -> Result<String, Utf8Error>` — copies
the bytes into a fresh refcounted String after validating UTF-8
(reject: invalid lead/continuation bytes, overlong encodings,
surrogates, > U+10FFFF, truncated sequences). `Utf8Error` carries the
byte offset of the first invalid byte. Probe `Data`'s current API for
the right accessor. Validation in Saw (std/string.saw), not the
compiler. Tests: valid ASCII, valid multibyte, each rejection class
(craft bytes via Data), offset correctness.

### 2. `bytes()` and `chars()` iterators (S1)
Following the VectorIterator pattern (struct + Iterator conformance,
usable in `for`):
- `bytes()` → iterator of byte values (probe the natural element type —
  match `byte_at`'s existing return type).
- `chars()` → iterator of Unicode scalar values decoded from UTF-8,
  yielded as Int (no Char type yet — document). Decoding shares logic
  with item 1's validator where practical. Since String contents are
  validated (literals are source-encoded; fromBytes validates), decode
  errors inside chars() should be unreachable — pick a defined behavior
  for corrupted-by-unsafe contents (stop iteration) and note it.
Iterator lifetime: the iterator holds its own String retain (ImplicitCopy
capture) so `for c in makeString().chars()` is safe — verify with a
temporary-receiver test.

### 3. `withCString` scoped borrow (S1)
`s.withCString { ptr in ... }` — non-escaping closure receives
`UnsafePointer<Int8>` to NUL-terminated bytes valid for the call's
duration. Probe the representation: if the refcounted payload is
already NUL-terminated, pass it directly (document the invariant where
the representation is defined); if not, allocate-copy-free around the
call. The closure param is non-escaping by default (brief 29) — that IS
the safety story; add an escape-attempt error test (storing the closure)
and a use test (strlen via FFI on the pointer).

### 4. Literal-side UTF-8 validation (S2 other half)
Probe: can an invalid-UTF-8 string literal reach codegen today (lexer
reads source bytes — try \x-style escapes if they exist, or raw bytes
in a scratch file)? If reachable, validate at lex/check time with a
clean diagnostic; if structurally unreachable (no byte escapes, source
must be valid UTF-8 to lex), document that as the guarantee and add the
escape-sequence TODO note only. Report the verdict.

### 5. StringBuilder modernization (S3)
Probe std/stringbuilder.saw's current state against the refcounted
String and Global allocation: it must (a) allocate through Global,
(b) produce a properly refcounted String from build() with no leak and
no double-free (deinit family oracle), (c) support append(String),
append Int (reuse the itoa path or format via interpolation), and
grow geometrically. Modernize in place; add ordering/content tests and
a build-then-mutate-builder independence test.

### 6. Docs
LANGUAGE_SPEC.md String section: the API additions, the UTF-8
guarantee statement, withCString + its non-escaping safety story,
chars()-yields-Int note. CLAUDE.md stdlib list line.

## Hazards
Refcount correctness — the string_*/deinit_*/implicit_copy_* families
are the oracle; -O0 spot checks on new lifetime tests (iterator retain,
withCString temporaries). Don't disturb the freestanding story: the new
APIs live in the alloc layer (std/string.saw), fine — but no new libc
externs beyond what string.saw already declares (validation is pure
Saw).

## Report back
Per item: mechanism, verification. Item 4's reachability verdict. The
representation finding from item 3 (NUL-termination invariant). Suite
tally; deviations; non-allowlisted commands.
