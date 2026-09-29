# Open questions for the user

The lead keeps this list while the user is away (user direction, Sep 29).
- **Reversible questions** are decided by the lead, with the Air's input, and recorded here as "decided, for review".
- **Fundamental questions** wait here for the user. Work that doesn't depend on them continues meanwhile.

Newest first within each section. When the user rules, the entry moves to "Resolved", with the ruling and where it is recorded.

## Waiting for the user (fundamental)

### W1. `borrow let x = e` in a `while` or `guard` head: an unwrap, or a borrow block condition? (Sep 29; found by the SL-426 batch)
SL:borrowing §2.4 (ruled, t21) makes a binding at an **`if`** head the optional-place unwrap: `if borrow var entry = e { … }`. It says nothing about `while` or boolean `guard` heads. There, GRAMMAR.md's head-reset admits a bare borrow block, so today the following parse with the block's value as the condition:
- `while borrow let e = m[k] { e.ok } { … }`
- `guard borrow let e = m[k] { e.ok } else { … }`

A borrow block's value is a copy, and a `Bool` copy is a valid condition, so these are real programs.

**The options:**
- **(a) Extend the unwrap to `while` and `guard` heads,** like `if`: `while borrow var e = it.find(&k) { … }` loops while the place is present, and `guard borrow let e = … else { … }` binds it for the rest of the scope. The bare block form there is then refused, as at `if` heads.
- **(b) Keep them as borrow-block conditions.** The §12 `cond` cell's P code would then be wrong for `while` and `guard` hosts, and gets recoded, as D2 did for `bhead`.

- **(a′) The split form of (a):** extend the unwrap to `while` only, where the borrow window is the loop body, as with `if`, and leave `guard` out.
  - **Why split:** under `guard`, `guard borrow var e = m.find(&k) else { return }` would hold the borrow to the end of the enclosing block. That is a new window shape, since every window today ends at a `}` or at the end of a statement, and every later use of `m` in that block would be an exclusivity error.
- **(c) Refuse, and decide later:** refuse the bare borrow block in `while` and `guard` heads, as §12's P code already says, and give the unwrap no meaning yet. The parenthesized `while (borrow let e = m[k] { e.ok }) { }` still spells the condition, and both meanings stay open. Like D2's first option, (c) is a new refusal rule.

**The Air's check (t2):**
- today the bare examples, and the parenthesized one, parse as conditions;
- the unwrap spelling `while borrow var e = it.find(&k) { e.count += 1 }` does not parse at all: it fails at the missing loop body;
- so no option silently changes a program's meaning, since under (a) today's bare-block programs become refusals.

**Why it waits:** the choice decides what these programs mean. Nothing is blocked until U4h, which parses borrow forms. The `if` host is already fixed (SL-426).

**The lead's recommendation:** (c) now, since it closes the unbacked P code without committing to either meaning. Then (a′) when a real loop wants to unwrap a place. `guard` stays out until its window shape has a design.

## Decided by the lead, for review (reversible)

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

**Decided:** accept the model. If SL-410 (the recognizer naming every refusing rule) produces a case that disagrees, the recognizer's name wins, and the parser follows it.

### D3. A checker rule refusing `try?` in `compiler/`, an S23-style exception (Sep 29; the Air's t20 on SL:hazards)
**The finding:** `try?` never releases the error it discards (SL-429, SL:hazards S3), and it reaches Stage 1 because the compiler is sync code. The leak ruling gives leak-only hazards no checker rule. You granted S23 an exception because a parser's hot paths would leak per token.

**Decided: add the rule** as the same kind of exception.
- **Why:** a parser's speculative "try this, else fall back" paths are where `try?` would naturally appear, so the leak would be per attempt. The rule is structural (refuse a `try?` expression), costs nothing today because `compiler/` has none, and its Instead is `match`.
- **Reversal:** delete the rule.

It is queued as a small side-queue item.

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

### D1. Autonomy settings for this stretch (user, Sep 29)
- **Decision policy:** as in this doc's header.
- **One agent at a time.**
- **The work order is the lead's to decide,** consulting the Air when useful. The current plan interleaves the parser units with side-queue items between units: SL-426, SL-410, SL-412, the lexer halves of SL-408 and SL-413, SL-405, SL-420 and SL-421.
- **Nothing is off-limits** unless the lead needs the user's feedback.
