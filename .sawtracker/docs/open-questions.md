# Open questions for the user

The lead keeps this list while the user is away (user direction, Sep 29).
- **Reversible questions** are decided by the lead, with the Air's input, and recorded here as "decided, for review".
- **Fundamental questions** wait here for the user. Work that doesn't depend on them continues meanwhile.

Newest first within each section. When the user rules, the entry moves to "Resolved", with the ruling and where it is recorded.

## Waiting for the user (fundamental)

None right now.

## Decided by the lead, for review (reversible)

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

### W2. The one-element tuple pattern (user, Sep 29): (b2)
**Ruling:** a one-element tuple pattern is spelled `(p,)`, as in expressions and types. A bare `(p)` in a pattern is refused, with a hint naming `(p,)`. No text silently changes meaning, and no real program in sawlang, sawtracker or sawos uses `(p)`.
- **GRAMMAR.md §8:** `tuple-pattern` gains the `(p,)` form, and `(p)` becomes a removed form with its fixit. §16 records sawc, which reads `(p)` as a one-tuple.
- **The parser:** U4e's one commented spot in `parse_tuple_pattern_body` flips, with its three pins.
- **Trailing comma (user, Sep 29): allowed.** A tuple pattern of any length takes one trailing comma, `(a, b,)`, as tuple expressions do. The Air's pin `case (a, b,)` flips from refused to accepted. **Tuples only (user, Sep 29):** a variant's payload list takes no trailing comma, so `Some(x,)` stays refused as a pattern, even though a call takes one when building the value (the Air, t4).

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
