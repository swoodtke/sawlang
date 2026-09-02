# Design 260 — Consuming Method Receivers (`consumes`)

**Status: AUTHORED Sep 1 2026** (lead), from the user's same-day spelling
ruling on DF-287c. USER-RULED: both-ends marking — the declaration carries
`consumes` in the post-parameter effect slot beside `unsafe`/`sync`/`borrows`,
and the CALL SITE is visibly consuming (the user's sketch was
`(consume obj).op(...)`; the ruled caller word is **`move`** — one word, one
job, already reserved — after the lead's identifier-breakage case:
`consume` is an ordinary and LIKELY identifier, sos's own motivating method
among them). Scheduled AHEAD of the queue by the user ("slot that in now")
for the next sos pin bump. **FULLY RULED (user, Sep 1, second pass): §3's Option A is
RATIFIED, and the receiver spelling is AMENDED — the declaration keeps
`&var self` (the exclusivity guarantees are `&var`'s; `consumes` does the
heavy lifting in the effect slot), NOT the lead's bare-`self` draft.**
Dispatch-ready (DISPATCHED same night). Filed record: DF-287c (matrix +
motivation). sos pin is at 0.3.0; **this lands as 0.4.0 (user, Sep 1: a new
language feature bumps MINOR — the standing pre-1.0 convention from here:
minor for new surface, patch for fixes).**

## 1. The surface

```saw
extension Builder {
    func finish(&var self) consumes -> Report { ... }     // declaration
    func close(&var self) consumes unsafe -> Int { ... }  // slot order: consumes unsafe sync
}

let report = (move b).finish()     // call: b is DEAD past this expression
```

- **Declaration (user-amended)**: the receiver stays `&var self` — the
  receiver grammar stays CLOSED at its two modes, and the Law of
  Exclusivity's path-charging covers the whole call exactly as for any
  `&var self` method; `consumes` in the effect slot is what changes the
  contract's ENDING (the exclusive borrow ends in the value's death: the
  callee is the release point, the caller's binding is moved-from after).
  Pairing: `consumes` REQUIRES `&var self` — on `&self` it is ``a consuming
  method needs an exclusive receiver — write `&var self` ``, on a free
  function or static it is a declaration error (nothing to consume), and
  bare `self` stays today's parse error everywhere. `consumes` is
  CONTEXTUAL (the slot position is unambiguous; the word stays an ordinary
  identifier elsewhere, like `type`/`private`). `consumes` and `borrows`
  are mutually exclusive (you cannot lend out of a receiver you destroyed)
  — a declaration error naming both.
- **Mechanically**: the receiver passes BY POINTER as every `&var self`
  does; what `consumes` adds is release responsibility (the callee deinits
  what remains of the referent at body end) and the caller-side
  moved-from marking. No relocation happens, which is cheaper than a
  by-value receiver for large types and is why the spelling is honest.
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

- **The caller spelling IS the transfer**, so three rules come FREE from
  `move`'s own axis: a `NoMove` receiver is refused at the CALL (`move` on a
  NoMove binding is already that axis's error — no new declaration-side
  check owed; whether in-place consumption of a NoMove type should ever be
  allowed, since nothing relocates under the `&var` shape, is RECORDED as a
  future question, not v1's); a Copy-tier receiver is legal and the call
  retires the binding exactly as `move` on Copy does; through a FIELD
  (`(move h.res).close()`) it is the no-partial-moves error with `take()`
  as the named escape, and through a PLACE the design-35 refusal with
  `swap_out` named.
- **A TEMPORARY receiver needs no `move`** — `make_builder().finish()` is
  legal bare: there is no binding to invalidate, and the temp was already
  the callee's to end. The fixit fires only when the receiver is a binding.
- **The callee releases the referent** — at body end the synthesized deinit
  runs over what remains of it, through the reference (a hand-written
  deinit body prefixes it, design 131, unchanged); the caller's binding
  performs NO release, ever, on any path.
- **The move checkpoint is the funnel** (obligation 1): the consuming call
  charges the receiver's root through `_check_value_transfer` exactly as a
  by-value argument does — this must NOT be a new synthesized-call path that
  skips it (DF-216a's mechanism; N10 is the standing warning).
- **Suspending consuming methods work** by construction — a by-value receiver
  is frame-resident like any owned param. Effects re-infer per instantiation
  as ever.

## 3. Field extraction out of a consumed `self` — OPTION A RATIFIED (user, Sep 1)

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

- **OPTION A — RATIFIED**: `move self.<field>` is legal INSIDE a consuming
  body, per field on an EVERY-path-or-NO-path rule — statically checkable
  with no drop flags, since the body's exits are known — and the callee's
  end-of-body release covers exactly the unmoved fields. Under the amended
  `&var self` receiver this is a `consumes`-licensed carve-out from BOTH
  standing bans it crosses (no-partial-moves AND no-move-out-of-a-ref):
  sound because the referent is the callee's to END — the caller's binding
  is moved-from on return and performs no release, so a partially-emptied
  state is never observable anywhere. Conditional per-path field moves stay
  refused in v1 (they are what would need drop flags); a diverging path is
  exempt from the all-paths test for the fields it never reaches, as in
  every liveness rule.
- Option B (Optional-wrapped fields, no carve-out) was DECLINED with A's
  ratification.

**DEINIT FOR A MOVED FIELD (amended Sep 1, on sos's question — the first
half restates the design, the second is a SOUNDNESS completion):**

1. **Synthesized deinit skips moved fields.** The end-of-body release
   covers exactly the unmoved remainder, in reverse declaration order
   among those fields; a moved field's value is released once, by its new
   owner, wherever it went. Statically decided — the all-paths rule is
   what keeps this flag-free.
2. **A type with a HAND-WRITTEN `deinit` body refuses `move self.<field>`**
   (Rust's E0509 analog, forced): design 131 makes the hand-written body
   PREFIX the synthesized drops, and that body is a black box that may
   read any field — running it against a moved-out field observes a dead
   value, and skipping it breaks the type's cleanup contract. The error
   fires at the `move`, names the type's `deinit`, and names the two
   outs: consume the receiver WHOLE (the hand-written body + full drops
   run at body end, unchanged), or extract through `self.field.take()` /
   `swap_out` — which MUTATE to a valid state (`None`, the swapped-in
   value) the deinit can legitimately see, and so stay legal on every
   type. Whole-referent `self = v` inside a consuming body is unaffected
   (the old referent deinits whole).

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
