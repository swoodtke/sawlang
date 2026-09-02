# Design 260 — Consuming Method Receivers (`consumes`)

**Status: AUTHORED Sep 1 2026** (lead), from the user's same-day spelling
ruling on DF-287c. USER-RULED: both-ends marking — the declaration carries
`consumes` in the post-parameter effect slot beside `unsafe`/`sync`/`borrows`,
and the CALL SITE is visibly consuming (the user's sketch was
`(consume obj).op(...)`; the ruled caller word is **`move`** — one word, one
job, already reserved — after the lead's identifier-breakage case:
`consume` is an ordinary and LIKELY identifier, sos's own motivating method
among them). Scheduled AHEAD of the queue by the user ("slot that in now")
for the next sos pin bump. **One cell open below (§3, field extraction) —
dispatch waits on it.** Filed record: DF-287c (matrix + motivation).

## 1. The surface

```saw
extension Builder {
    func finish(self) consumes -> Report { ... }       // declaration: paired
    func close(self) consumes unsafe -> Int { ... }    // slot order: consumes unsafe sync
}

let report = (move b).finish()     // call: b is DEAD past this expression
```

- **Declaration**: receiver spelled bare `self`, effect slot says `consumes`,
  and the two REQUIRE each other (the `unsafe static var` pairing precedent —
  each half alone is a clean error): bare `self` without `consumes` stays
  today's parse error verbatim; `consumes` beside `&self`/`&var self` is
  ``a consuming method takes its receiver by value — write `self` ``.
  `consumes` is CONTEXTUAL (the slot position is unambiguous; the word stays
  an ordinary identifier everywhere else, like `type`/`private`).
  `consumes` and `borrows` are mutually exclusive (you cannot lend out of a
  receiver you destroyed) — a declaration error naming both.
- **Call**: `(move b).finish()` — `move` in receiver position, parenthesized,
  on the `(&x) as UnsafePointer<T>` operand-then-postfix precedent. The bare
  `b.finish()` on a consuming method is refused with the mirror fixit
  (``error: `finish` consumes its receiver — write `(move b).finish()` ``),
  exactly as `&var` mismatches are. After the call the binding is moved-from:
  every later use is the ordinary use-after-move error, a moved `var`
  revives on reassignment.
- **Chaining**: the RESULT is an owned value; `(move b).finish().len()`
  works. A consuming call in the middle of a chain consumes only the
  receiver expression's binding.

## 2. Rules that follow from existing law (no new machinery)

- **Consumption is a move**, so: a `NoMove` receiver type REFUSES a consuming
  method AT THE DECLARATION (derivation rule, TaskGroup's family, not a
  per-type check); a Copy-tier receiver is legal and the call retires the
  binding exactly as `move` on Copy does; through a FIELD
  (`(move h.res).close()`) it is the no-partial-moves error with `take()` as
  the named escape; through a PLACE (`(move v[i]).close()`) the design-35
  refusal with `swap_out` named.
- **The body owns `self`** — an owned binding, the callee's to release: fall
  off the end and the synthesized deinit runs there (a hand-written deinit
  body prefixes it, design 131, unchanged).
- **The move checkpoint is the funnel** (obligation 1): the consuming call
  charges the receiver's root through `_check_value_transfer` exactly as a
  by-value argument does — this must NOT be a new synthesized-call path that
  skips it (DF-216a's mechanism; N10 is the standing warning).
- **Suspending consuming methods work** by construction — a by-value receiver
  is frame-resident like any owned param. Effects re-infer per instantiation
  as ever.

## 3. THE OPEN CELL — field extraction out of a consumed `self` (USER)

The motivating API is `finish()` RETURNING what the builder accumulated —
which for a NoCopy field means moving it OUT of `self`:

```saw
struct Builder { items: Vector<Int>, count: Int }
extension Builder {
    func finish(self) consumes -> Vector<Int> {
        move self.items          // ← the question
    }
}
```

Today `move self.items` is the no-partial-moves error, and WITHOUT an answer
a consuming method cannot extract a plain NoCopy field at all (the field
would need to be stored as `Optional<Vector<Int>>` just to `take()` it —
wrapping storage to satisfy a spelling, which is the tail wagging the dog).

- **OPTION A (lead RECOMMENDS): `move self.<field>` is legal INSIDE a
  consuming body, UNCONDITIONALLY per field.** The rule: each field is
  moved-out on EVERY path or on NO path — statically checkable with no drop
  flags, since the body's exits are known — and the synthesized deinit at
  body end releases exactly the unmoved fields. This is the carve-out's
  soundness story: `self` is the CALLEE's owned value and nobody observes it
  after, so partial states never escape; the no-partial-moves rule exists to
  protect OBSERVABLE bindings, and a consumed receiver is not one.
  Conditional per-path moves stay refused in v1 (that is what would need
  drop flags); a diverging path (panic/return-early) is exempt from the
  all-paths test on the fields it never reaches, same as every liveness rule.
- **OPTION B (smaller, weaker): no carve-out.** Extraction goes through
  `Optional.take` / `swap_out`, i.e. APIs wrap their extractable fields in
  `Optional`. Builds today's machinery only; makes the feature far less
  useful for exactly its motivating shape.

## 4. v1 fences (each a clean error naming the fence)

- **No trait-requirement `consumes`** in v1 (the `borrows` v1 precedent —
  "no trait requirements"); a conformance kind-mismatch error stands ready.
- No consuming methods on ENUM receivers in v1? NO — enums are IN (they take
  extensions and the semantics are identical); the fence list deliberately
  does not include them.
- `FuncPointer`/function-type spelling: out of scope (methods are not
  first-class).
- `deserialize`-style statics unaffected (no receiver).

## 5. Expected closures + follow-ons (recorded, not this brief's)

`Task`/`Thread` `join`/`detach`/`cancel` migrate from design 242's runtime
provenance panics to compile-time consumption — a separate migration brief
AFTER this lands (it flips a std behavioral contract and owes obligation 2's
sweep). `Optional.take`-shaped APIs may simplify. The saw-lang skill, spec
and README all gain the feature (design 125 convention).

## 6. Units

- **U0 — conformance rows first** (obligation 3: this is an ownership-safety
  surface): rows for double-consume-is-a-compile-error, use-after-consume,
  NoMove-refusal, and (under Option A) the all-paths field-move rule.
- **U1 — the feature**: lexer-untouched (contextual word), parser (paired
  receiver/slot + the `(move expr)` receiver form), typechecker (third
  receiver mode through the move-checkpoint funnel; Option A's per-field
  rule if ratified), codegen (by-value receiver — the passing convention
  largely exists; ownership/drop responsibility moves), diagnostics with
  mirror fixits both directions.
- **U2 — docs + pins**: LANGUAGE_SPEC, skill, README; pins for every §2 rule
  and §4 fence.

Gates: per-commit suite + freestanding; terminal battery. Serializes with
the compiler pipeline (typechecker surface — nothing else may be on it).
