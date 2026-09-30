# Open questions for the user

The lead keeps this list while the user is away (user direction, Sep 29).
- **Reversible questions** are decided by the lead, with the Air's input, and recorded here as "decided, for review".
- **Fundamental questions** wait here for the user. Work that doesn't depend on them continues meanwhile.

Newest first within each section. When the user rules, the entry moves to "Resolved", with the ruling and where it is recorded.

## Waiting for the user (fundamental)

None right now.

## Decided by the lead, for review (reversible)

### D12. Resolve binds builtins to a synthetic `builtin` module, and the prelude is an inclusion table (Sep 30; the Air, SL-445 c1)
§3.3's binding kinds have no slot for the declarations nothing declares: the primitive types, `String`, the Stage-0-synthesized `Optional`/`Result`, `print`/`panic`/`assert`/`sizeof`/`alignof`, and `Void`/`Never`. Stage 0 also defines the prelude by exclusion (`IMPORT_REQUIRED_STD_*`).

**Decided:**
- Builtins are declarations of a synthetic `builtin` module, one table, and bind like any other: `String` is (builtin, String).
- The prelude is one inclusion table in resolve (design 82's curated core), checked once against Stage 0's computed set over today's std. The design-255 gated tier derives from it.
- An inclusion list fails safe: a new std module is gated by default.

**Reversal:** a different home for builtins (for example, the new std declaring them), or an exclusion list.

### D11. `syntax.lex.ascii-identifier` covers every non-ASCII character outside strings and comments (Sep 30; the Air, SL-410 c4)
§2.7 words the rule as "a letter outside ASCII cannot start or continue [an identifier]". sawc2's lexer refuses every non-ASCII character outside a string literal or a comment alike, as "Unexpected character": `é`, `ï` and `→` all get that. Naming the rule only for letters needs a Unicode letter table in the subset.

**Decided:** reword §2.7. Saw source is ASCII outside the text of string literals and comments, and an interpolation's expression is source (the Air, c6). Any other character there is refused as `syntax.lex.ascii-identifier`. The message names the character and says that identifiers and source outside strings are ASCII.
- Every such character is refused either way, so only the name changes. No program changes meaning.

**Reversal:** narrow the rule to letters with a letter table, and give a non-letter its own name.

### D10. A `{` right after `while` opens the infinite loop's body (Sep 29; U4i)
GRAMMAR.md is ambiguous at `while {`. The recognizer accepts `while { a } { }` as `While.conditional` with a closure literal as its condition. It finds `while { a }`, then a line break, then `{ }` ambiguous, since the infinite loop followed by a closure statement is also a tree. sawc2 and the frozen compiler both read `while {` as the infinite loop, and 81 tracked files use that form.

**Decided:** add a §13 rule that a `{` right after `while` begins the infinite loop's body, never a condition. The recognizer gets the matching filter. A closure condition either can't typecheck, since a closure is not a `Bool`, or it is refused. An immediately called closure, `while { check() }() { step() }`, would typecheck under the old reading, but under D10 the `{` opens the body, so the text is refused rather than re-read (the Air, t6). The frozen compiler refuses it the same way. So no program silently changes meaning.
- **To pin:** `while { c }() { }` is refused by the new rule's name, and `while ({ c }()) { }` is accepted as a conditional loop.
- **sawc2 changes too** (the Air, t7). Today sawc2 refuses the first at the `(` as `block-tail`, whose hint, "parenthesize the loop to use its value", points the wrong way. The unit makes sawc2 name the new rule at that token instead, with the hint `while ({ check() }()) { step() }`. The frozen parser's refusal of the second pin is §16's existing `syntax.expr.call` row (SL-73), not a D10 matter.

**Reversal:** drop the rule and parenthesize, as in `while ({ a }) { }`.

### D9. Std accessors whose body only reads get a shared twin (Sep 29; SL-421)
SL:borrowing rules twins for `Vector.[]`, `Vector.find` and `KeyedPlace.find` only. tests/corpus reads six more std accessors in a shared position: a `let` root, a `&` param or a capture of a `let`.
- `JsonValue.as_array` and `as_object`;
- `Map.[]` (the place accessor);
- `Box.value`;
- `std.compiler.frame` `Slot.value`;
- `UnsafeRef.deref`.

Each is declared `(&var self)` in the frozen std, and each body only reads: it matches or guards, then lends.

**Decided:** in the new std, a std accessor whose body only reads gets a `@synthesize(shared)` twin (§4), so these six serve `borrow let` on shared roots. SL-421's corpus decisions assume it.

**Reversal:** give one of them no twin, and re-aim its corpus files as refusals, or respell them through a mutable root.

### D8. Getitem and setitem derivation with an accessor pair (Sep 29; SL-420 finding 4)
§5.2 states the derivation for a type that declares "only the place accessor". **Decided:** a type that declares a pair derives getitem from the `&self` accessor and setitem from the `&var self` one. That is the reading SL-420's re-aims use. **Reversal:** restrict derivation to single-accessor types.

### D7. What the root column of SL:borrowing §3's table means (Sep 29; SL-420 finding 3)
§3 says `(&self) borrows -> &var T` (`Mutex.lock`) holds its root "exclusive", yet `lock()` must work on `let`, `&self` and static roots (§8, §8a). **Decided:** the column is the *overlap* charge: no other use of the root while the borrow is open, so `m.lock()` inside its own window is refused, as §8 says. Whether the root must be *mutable* comes from the receiver. A `&var self` accessor needs a mutable root; a cell accessor takes `&self`, so `let`, `&self` and static roots serve. The clarification is in SL:borrowing §3 (r24). **Reversal:** a cell accessor would need a mutable root, which contradicts §8a.

### D6. How a signed width suffix bounds a literal (Sep 29; the Air, SL:hazards t21; SL-435)
GRAMMAR.md §2.7 `syntax.lex.int-range` says a literal must fit "in its suffix's width", but not how a signed width counts. Stage 0 and sawlex both check the unsigned range, so `255_i8` lexes, and Stage 0 wraps it to -1 (S7's signed-suffix face).

**Decided:** state it in two layers.
- **The lexer** checks the width's unsigned range, so `256_u8` and `256_i8` are lexical errors.
- **A later stage** holds a signed suffix's literal to the signed range. It allows exactly 2^(w−1) as the operand of a unary minus (`-128_i8`), since the lexer cannot tell a negation from a subtraction.
- §16 gains a `defect` row for Stage 0's silent wrap.

**Why reversible:** it only refuses programs that silently wrap today. It changes no meaning a correct program has. The subset checker gets the matching rule (SL-435).

**Reversal:** reword §2.7.

### D5. The depth limit decides no reading (Sep 29; U4c)
A speculative generic list that the depth limit cuts short is refused with `syntax.rule.depth-limit`. It is not re-read as comparisons, because otherwise the depth budget could change what a program means. A speculation that fails for any other reason still gives its levels back, and a depth cell pins that.

**Decided:** as implemented in U4c (merged ee6d0143). The Air confirmed that making the refusal final is right: `g(a < b, b < c, c >> (d))` is a generic call, so a re-read could change meaning.
- **Refined (the Air's review of p3):** a *flat* valid program, `f(x0 < x1, …, x256 < x257)`, was refused because each pair speculated one nested list.
- **Fix, queued at the start of U4d:** skip speculating when no closing `>`, `>=`, `>>` or `>>=` comes before the enclosing bracket closes, since such a list could never close. That accepts the flat case and keeps D5 for the balanced one.
- **Also queued:** GRAMMAR.md §11 will state that a speculated list charges depth while its contents are parsed, and that a list cut short by the limit is refused. A cell pins the flat case.

### D4. When the parser names a refusal `generic-or-less` (Sep 29; U4c)
Suppose a list parses and the follow rule rejects it. If the token after its `>` can continue the expression (`continues_postfix`), and the comparison re-read then fails with a plain error or a comparison chain starting at that `<`, the parser reports `syntax.rule.generic-or-less` at the `<`. Otherwise the comparison reading's own error stands, so `a < b > c` stays `refused-compare-chain`. The Air checked 12 shapes in SL-424.p3's review: where the reference names a rule, the parser names the same one at the same `<`.
- **Evidence:** this matches every corpus case and U4c's differential of about 200 texts: `a<b>` before a line break, `a<b> - 1`, `a<b>[0]`, and `x as T<a, b> c` staying `parse-error`.
- **Caveat:** it is a model of the recognizer's "the chart accepts, a filter refuses" condition, not a derivation of it.
- **Correction (the Air, SL-424 c31):** the 12-shape check compared against the reference's raw "refused by" rule, which is README Refusals step 3. Step 2 comes first: a removed production whose enabling alone makes the text parse. Under step 2, `a<b> - c` and `a<b>[0]` are expected to be recorded as `refused-compare-chain`, since each parses as a chain once chains are enabled. U4d fixes the parser to follow the classification, and sweeps the shapes with `cases.py`.
- **As implemented in U4d (SL-424.p4):** when re-reading a rejected list as comparisons gives a chain that parses whole, the parser reports `refused-compare-chain`. Otherwise `generic-or-less` stands, under the `continues_postfix` condition above.
  - In 26 shapes, the chain flips are `- c`, `[0]`, `* c`, `& c`, `.. c` and `-(c)` after the `>`.
  - `!` and a line break keep `generic-or-less`.

**Decided:** accept the model. If SL-410 (the recognizer naming every refusing rule) produces a case that disagrees, the recognizer's name wins, and the parser follows it.

### D3. A checker rule refusing `try?` in `compiler/`, an S23-style exception (Sep 29; the Air's t20 on SL:hazards)
**The finding:** `try?` never releases the error it discards (SL-429, SL:hazards S3), and it reaches Stage 1 because the compiler is sync code. The leak ruling gives leak-only hazards no checker rule. You granted S23 an exception because a parser's hot paths would leak per token.

**Decided: add the rule** as the same kind of exception.
- **Why:** a parser's speculative "try this, else fall back" paths are where `try?` would naturally appear, so the leak would be per attempt. The rule is structural (refuse a `try?` expression), costs nothing today because `compiler/` has none, and its Instead is `match`.
- **Reversal:** delete the rule.

Landed in SL-432.p1, which the Air approved.

### D2. SL-426's `bhead` cell: recode §12 from P to S (Sep 29; the Air's t1)
Correction: the lead first wrote "B", which is not a §12 code. The SL-426 agent used **S** ("parses; a later stage refuses the construct in this position"), whose legend matches this decision's reason word for word. Y is the alternative, since a borrow head "may be any expression" (SL:borrowing §2.1). Either is one character, and the generator treats them alike.
**The finding:** §12 codes `syntax.borrow.block` × `bhead` as P (parenthesized only). But `syntax.rule.head-reset` admits a nested borrow construct's body in any head (SL-426 c1), so GRAMMAR.md's text says `borrow let x = borrow let x = a { x } {` parses. The recognizer agrees.

**The options:**
- (a) a new refusal rule, which would be a new language rule and so the user's call;
- (b) recode the cell S, a §12 correction that matches the text.

**Decided: (b).** The type layer refuses the case either way, since a block's value is not a place, so no program changes meaning.
- **Reversal:** a later ruling for (a) adds the rule and flips the cell back.
- **`cond`,** SL-426's other cell, is a plain recognizer fix: borrow-form's "at an `if` head … unwrap" clause already backs its P.
- Both land when SL-426 is dispatched, before U4h.

## Resolved

### W3. An absent conditional write evaluates its right side (user, Sep 29): (a)
**Ruling:** `borrow var v.find(9)?.value = loud(3)` calls `loud(3)` whether or not the place is present. Every assignment has one order: the right side first, then the left borrow. `?` skips only the write. The block form `if borrow var p = v.find(9) { p.value = loud(3) }` computes the value only when present.
- **Recorded in:** SL:borrowing §2.2 (r24).
- **This changes today's optional chaining,** which skips the right side (LANGUAGE_SPEC, Optionals: "the RHS is skipped entirely on short-circuit"). GRAMMAR §15 lists the passage (SL-437).
- **No real program uses it** (the Air, t5). The tests/corpus files that pin the skip are re-aimed in SL-438, `place_assignment_targets` among them.

### W2. The one-element tuple pattern (user, Sep 29): (b2)
**Ruling:** a one-element tuple pattern is spelled `(p,)`, as in expressions and types. A bare `(p)` in a pattern is refused, with a hint naming `(p,)`. No text silently changes meaning, and no real program in sawlang, sawtracker or sawos uses `(p)`.
- **GRAMMAR.md §8:** `tuple-pattern` gains the `(p,)` form, and `(p)` becomes a removed form with its fixit. §16 records sawc, which reads `(p)` as a one-tuple.
- **The parser:** U4e's one commented spot in `parse_tuple_pattern_body` flips, with its three pins.
- **Trailing comma (user, Sep 29): allowed.** A tuple pattern of any length takes one trailing comma, `(a, b,)`, as tuple expressions do. The Air's pin `case (a, b,)` flips from refused to accepted. **Variant payloads too (user, Sep 29, revising "tuples only"):** a variant's payload list also takes an optional trailing comma, so `Some(x,)` is accepted, matching the call that builds the value (the Air, t4). The user's reason: refusing it slightly complicates parsing and buys nothing. U4e's `case Some(x,)` pin flips to accepted.
- **One element:** in a tuple pattern the comma stays required (`(p,)`, with `(p)` refused). In a payload it is optional: `Some(x)` and `Some(x,)` are the same.

### W1. `borrow` bindings at `while` and `guard` heads (user, Sep 29): (a) for `while`; `guard` takes none
**Ruling:** a borrow binding at a `while` head is the optional-place unwrap, as at `if`: `while borrow var e = it.find(&k) { … }` loops while the place is present. A `guard` takes no borrow binding (the user: "Guard can't use borrow since its body is in the else").
- **`while`:** the window is the loop body. The head is evaluated again each iteration, after the previous window closes. The bare borrow-block condition is refused there, as at `if`. The parenthesized `while (borrow let e = m[k] { e.ok }) { }` stays a condition.
- **`guard`:** a borrow binding in its head is refused by name, with a hint pointing at `if borrow … { } else { … }`. The parenthesized block stays a boolean condition.
- **To update:** SL:borrowing §2.4, GRAMMAR.md §9 (where a binding stands), `syntax.rule.borrow-form`, and §12's `cond` cells, with corpus cases for both hosts.

### D1. Autonomy settings for this stretch (user, Sep 29)
- **Decision policy:** as in this doc's header.
- **One agent at a time.**
- **The work order is the lead's to decide,** consulting the Air when useful. The current plan interleaves the parser units with side-queue items between units: SL-426, SL-410, SL-412, the lexer halves of SL-408 and SL-413, SL-405, SL-420 and SL-421.
- **Nothing is off-limits** unless the lead needs the user's feedback.
