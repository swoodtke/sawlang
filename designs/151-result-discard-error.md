# Design 151 — discarding a `Result` is an error; `let _ =` is the explicit discard

**Status: APPROVED (user, Aug 6): "making Result discard explicit and
an error otherwise sounds good to me." Queued right after 150 (both
tree-touching; before the [138 ∥ M1-adoption] finale so the docs sweep
documents it and the adoption pass picks up the spelling).**

## Decision [user]

An expression whose value has type `Result<_, _>` and whose value is
discarded is a **compile error**. The explicit discard is `let _ =
expr` — the spelling the design-122 hints already bless. This closes
the last silent-drop in the language: today
`visit_ExpressionStatement` (typechecker/statements.py ~933) checks a
statement expression and throws the type away, so
`stream.write(data)` as a bare statement drops its `Result` with no
diagnostic — against the standing never-hide-errors principle and the
design-131 rule that no status is ignorable.

## Scope (pinned)

1. **Result only.** Optionals and every other type stay freely
   discardable (dropping a Map-insert's returned old value is normal;
   `?.` chains typed `Void?` stay statements by design 111). No
   `@discardable`/must-use attribute system — under house rules a
   Result you may always ignore should not have been a Result; if a
   genuine need appears later it is a new design, not a hole here.
2. **Every implicit-discard position**, not just expression
   statements: the agent enumerates them (expression statement; a
   non-tail `match`/`if` in statement position whose arms produce
   Results; a block final expression discarded in a `Void`-returning
   context — whatever the checker permits today). One rule everywhere:
   a Result value that no construct consumes is an error.
3. **Erased results included**: `Result<T, Box<any Error>>` is a
   Result. Suspending calls included (the check is on the checked
   type, not the call form).
4. **`try!`/`try` are consumption**: `try! f()` yields `T`;
   discarding the `T` is fine (unless `T` is itself a Result — then
   the rule applies to it).
5. **Diagnostic contract**: names the type and both outs — "result of
   `write` is `Result<Int, IoError>` and is silently discarded —
   handle it, or write `let _ = ...` to discard explicitly."

## Migration

Audit every tree site the new error fires on (std, blade, libs,
examples, sos, selfhost). Each is either (a) a genuine bug — handle
the error properly (never-hide-errors: this is the expected majority
outcome and each one is a finding worth a line in the tracker), or
(b) a deliberate discard — `let _ =` with a trailing comment iff the
reason is not obvious. No blanket mechanical `let _ =` sweep: that
would launder exactly the bugs the rule exists to catch.

## Tests / gates

Error fires: bare statement call returning Result; erased Result;
suspending Result call; match-arm discard; Result-typed `T` from
`try!` re-discarded. Stays legal: `let _ =` discard; Optional
discard; `Void?` chain statement; Void calls. Full battery: suite
(zero xfails), lexdiff, astdiff, irdet --all (venv), bootstrap,
sos_runner.
