# Design 32 — Equality: Equatable mirroring the Copy family

**Status: DECIDED (Jul 28, user).** Source: tracker D2 (critique concern
5); also resolves S4 (String equality). Ruling:

- **`Equatable` trait gates `==`/`!=`.** Conformance mirrors the Copy
  family's house rule exactly:
  - **Auto-conform:** trivial (POD) structs — the same set that
    auto-conforms to `Copy` — and payload-free enums. Primitives
    (integers, Bool, Float) and `String` conform builtin.
  - **Opt-in with synthesis:** everything else declares
    `extension T: Equatable {}`; an empty body synthesizes memberwise
    `==` for structs and payload-deep `==` for enums (tag, then active
    payload fields). A custom implementation overrides synthesis.
  - Resource types (`File`, `Mutex`, ...) never conform — nonsense
    equality is unrepresentable, not just discouraged.
- **Enum equality becomes payload-deep**, fixing the tag-only bug
  (`Msg.Write(text: "a") == Msg.Write(text: "b")` is currently TRUE;
  under this design payload enums have no `==` until conformance is
  declared, and then it is deep).
- `!=` is always the negation of `==`. Float keeps IEEE semantics
  (`NaN != NaN`) — synthesized `==` over a Float field inherits this.

## Implementation items

1. **Trait + desugaring.** `Equatable` in builtin.saw:
   `func equals(&self, other: &Self) -> Bool` (avoids inventing operator
   overloading — `a == b` on conforming user types desugars to
   `a.equals(&b)`; primitives keep direct icmp/fcmp codegen). String's
   existing `equals` in std/string.saw becomes its conformance.
2. **Auto-conformance** for trivial structs + payload-free enums —
   piggyback on the existing auto-Copy triviality machinery (same
   predicate; keep them in one place). Payload-free enum `==` keeps its
   current tag-compare codegen.
3. **Synthesis** on empty `extension T: Equatable {}`: memberwise for
   structs (field-by-field `&&`, using each field's Equatable — error
   naming the first non-conforming field if any); payload-deep for
   enums (tag check, then per-variant field comparisons; wildcard-safe
   for payload-free variants).
4. **Migration audit (breaking change, handle honestly):** payload
   enums lose tag-only `==`. Find every existing test using `==` on
   payload-carrying enums (enums_equality.saw etc.); update each to
   declare conformance — noting where deep semantics CHANGES the
   expected output (that delta is the bug being fixed; report each
   flip). Match-based code is unaffected.
5. **Generic bound:** `T: Equatable` grants `==`/`.equals` in generic
   bodies via the brief-24 bound-aware method resolution (should fall
   out; test it: generic `contains<T: Equatable>` over Vector).
6. **Tests:** auto cases (trivial struct, payload-free enum), synthesized
   cases (String-bearing struct; payload enum deep true/false), custom
   override, non-conforming field error, `==` on a non-Equatable type
   error, NaN behavior, generic-bound usage.
7. **Docs:** LANGUAGE_SPEC.md equality subsection; CLAUDE.md trait list.
8. **Stretch (probe, skip if nontrivial):** tuple equality for
   equatable element types.

## Hazards
The enum-== change is the one behavioral break — the migration audit is
the oracle-with-eyes-open. Synthesis must not fight the typechecker's
conformance checking (empty extension body currently means "missing
methods" errors — the synthesis hook must run before that check).

## Report back
Per item: mechanism, verification. Every payload-enum test whose
expected output flipped (item 4). Whether tuples made it. Deviations;
non-allowlisted commands.
