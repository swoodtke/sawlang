# M16: unchanged lexer acceptance (SL-259)

Build on merged M15. The acceptance subject is the exact current bytes of
`selfhost/lexer/src/lib.saw`, followed by a small driver. Do not rewrite the
lexer to fit the prototype. Implement missing subset features in the prototype;
file production compiler findings rather than reproducing them.

## StringBuilder.clear

Add `BuilderClear`: dst/b/target unused (-1), immediate 0, empty args; a is a
mutable reference to Builder. Source `builder.clear()` takes no arguments,
returns Void and uses the same named receiver/exclusivity rules as append.
It empties existing content, preserves all previous build() snapshots, and
supports repeated clear and append-after-clear. It performs no recoverable
allocation and does not consume the deterministic append-failure counter.
VM/native must preserve the live builder identity and avoid leaking old bytes.
The VM's own infrastructure allocation limitations remain documented.

## Bare break in conditional while

Support statement `break` targeting the nearest enclosing while body. A loop
context records lexical depth plus unresolved break jumps. Before jumping, drop
owning slots introduced inside that loop body, including nested scopes, without
dropping outer locals. Patch jumps to the loop exit. Nested loops target their
own exit. Continue, break-with-value, labeled breaks and loop expressions remain
outside this slice, with located rejections. A break does not prove that its
containing function returns a result; do not conflate loop exit with return in
value-control flow. Either distinguish abrupt outcomes or conservatively reject
unsupported value-expression placements. Clear loop contexts between functions.

Tests: ordinary/nested/conditional breaks, owning cleanup, outer value survives,
zero iterations, return after break, and non-Void fallthrough remains rejected;
break outside loop, break value and continue rejected. Keep existing move limits.

## Statement match expression arms

The unchanged lexer also uses `case Text -> try! out.append(...)` without a
brace block. Admit expression arms in statement enum/String/Result matches,
evaluate each selected expression once, and clean its owning temporaries. This
does not create a value join. Preserve the Result-discard rule: unhandled append
results must be refused, while try! append yields Void and is legal. Test each
subject family, owning cleanup, and rejection of discarded Result values.

## Nonbinding discard declarations

The lexer repeatedly writes `let _ = self.advance()`. `_` must not enter the
local binding table or cause duplicate-name errors. Evaluate each initializer
once, honor any type annotation, and dispose of owned discarded values safely.
Explicit discard admits Result and Void; it does not make `_` readable later.
Test repeats, observable evaluation order, owning values and Result/Void, plus
undefined `_` use and incorrect annotations.

## Integration and differential gate

A Python harness concatenates the untouched lexer and a generated driver using
the admitted subset. Canonical output includes every token's kind, raw byte
value, line, column, optional suffix and segment indices; every doc-comment and
string-segment field; and lexical error message/position. Encode String values
as byte lengths plus individual byte values so NUL/newline/delimiters cannot
hide differences. Compare exact output from the prototype VM, its LLVM/native
path, and Python-sawc-built same source. Include independent golden cases so
three consumers do not share an unnoticed serializer omission.

Corpus selection is explicit and reproducible: lexer tests, representative
tracked Saw sources (including the lexer itself), and generated lexical edge
cases. Offer a larger corpus mode separately; record actual coverage/counts.
Build the full lexer in every mode; no helper-only acceptance. Preserve input
bytes through generated Saw literal escaping. Bound runtime with configurable
VM budget and subprocess timeouts; classify timeouts and divergences as failures.
Native owning cases also run under ASan. Run all prior prototype cases.

## Scope ledger

Create COMPATIBILITY.md with known unsupported features, semantic differences,
required future work, owning design/issue, and covering tests. Explicitly record
snapshot Vector reads vs production borrowing places and Copy-only elements;
general borrowing/moves/generics/recursive representation/coroutines stay future
work. Separate implemented subset restrictions from full-language parity claims.

## Division of work

Sol frontend owns frontend.saw and new focused source fixtures/harness entries
for clear/break. Sol runtime owns model/verify/vm/llvm and runtime helpers for
BuilderClear plus its independent contract. Sol implements the whole-lexer
harness from this design; parent authors the ledger, integrates, reviews and
corrects the implementation, validates and submits.

## Validation record

M16 passed all 439 prototype cases, including 15 completion cases and 13 focused
sawc comparisons. The unchanged lexer passed the 39-input default corpus and
100 additional tracked-source inputs through VM, native O0/O2/ASan and the
same-source sawc-built lexer. Five complete hand-authored canonical records
cover empty input, simple tokens, an error, doc trivia and interpolation.
BuilderClear's independent contract passed VM/native O0/O2/ASan, including
snapshot preservation and failure-counter behavior. Citation and diff checks
passed. This is bounded corpus coverage, not full Saw conformance.

Commands beyond the README's default gates:

```sh
python prototypes/minivm/test_lexer.py --binary .build/minivm/minivm \
  --large --large-limit 100 --case-prefix large/ --vm-budget 200000000 \
  --timeout 600 --compile-timeout 600
python prototypes/minivm/test_minivm.py --binary .build/minivm/minivm \
  --section lexer_completion --sawc sawc/sawc.py
```
