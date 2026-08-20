# Design 236 — `static` Is Required: No Inferred Staticness

**Status: BUILT Aug 20 2026** (branch `design-236`, six units). Ratified
Aug 18 (user ruling: "static is required to define a static method — no
inference"); queued BEFORE design 235, whose matrix ledgers would otherwise
have pinned the keywordless grammar and needed immediate re-rows.

Landed: the grammar (`_parse_static_modifier`, two entry points), the three
declaration errors through the `_check_static_declaration` funnel,
conformance kind agreement in `_check_trait_conformance`, the `--emit-docs`
static bit (schema 2 -> 3), the whole-corpus migration (118 declarations;
sos/, devtools/ and selfhost/ had none), and the position matrix as
`examples/errors/static236_*` plus two positive pins. One V39-alike found:
blade's `self.layout.clean_all()`. One finding filed: DF-236a, DF-217q's
call-site refusal missing a field-access receiver.

## The decision

A method with no receiver is no longer silently a static. The `static`
keyword is REQUIRED on every static method declaration, and a self-less
`func` without it is a DECLARATION-SITE error:

```saw
extension Point {
    static func origin() -> Point { Point(x: 0, y: 0) }   // declared static
    func mag(&self) -> Int { ... }                        // instance method

    func dup(x: T) -> T { ... }
    // error: method `dup` has no receiver — add `&self`/`&var self`,
    //        or declare it `static func` if a static was intended
}
```

## Why

Staticness WAS fully determined by the missing receiver, so inference
doctrine permitted it — but reader-visibility trumps (the call-site `&var`
precedent), and the V39 incident (Aug 17, DF-217q's consumer sweep) showed
the inference silently converting an authoring MISTAKE into a different
kind of method: a conformance row wrote `func dup(x: T)` intending an
instance method, forgot the `&self`, and got a static that only resolved
through a broken call path. The keyword converts forgot-`&self` into the
right error at the right place. It also completes DF-217q from the other
end: the call site already reads `Bag.solo(...)` (type-explicit, ruled Aug
17); now the declaration carries the same word.

## Rules

1. **Grammar**: `static func` in extension bodies (struct AND enum — design
   145 gives enums statics on the same terms). `static` here is the same
   keyword as design 149's `static` module variables in a new position;
   member-head vs declaration-head keeps the parser unambiguous.
2. **The error**: a self-less non-`init` `func` in an extension is refused
   at the declaration with the two-way fixit (add a receiver / write
   `static`). A `static func` WITH a receiver is the mirror error.
3. **`init` is exempt** — it is already its own declaration kind and takes
   no receiver by construction; writing `static init` is an error.
4. **Traits**: a trait requirement that is static spells `static func` too,
   and conformance matching requires the kinds to AGREE (a static
   requirement is satisfied only by a static, an instance requirement only
   by an instance method). Matrix rows both ways.
5. **Docs/`--emit-docs`**: the JSON surface gains/keeps the static bit from
   the keyword rather than the receiver's absence.

## Position matrix (obligation 1)

Declaration positions: struct extension method, enum extension method,
trait requirement, trait default body, generic extension's method,
`@export`'d function (module-level funcs are NOT methods — untouched),
runtime-build seams (module-level — untouched). Error rows: self-less
without `static`; `static` with `&self`; `static init`. Positive rows:
`static func` declared + type-called; instance method unchanged.

## Migration (obligation 2)

Compiler-driven: after the grammar lands, every existing self-less
extension method in the corpus is the new declaration error — std, blade/,
libs/, sos/ (kernel + sysapi + sosrt), devtools/, examples/. The sweep adds
`static` where intended (the overwhelming case) and catches any latent
forgot-`&self` V39-alikes (each one found is a bug fixed by the migration
itself — record any in the landing note). Mechanical, one commit per tree
region, suite + sos gated (sos/ is in the blast radius).

## Interaction notes

- **DF-216c** (generic statics never instantiate their type parameters) is
  INDEPENDENT — the keyword names the path but does not fix it; its pin
  (`examples/generic_static_type_arg_inference.saw`) gains the keyword in
  the migration and stays XFAIL until the static generic path is fixed.
- **Design 235** runs AFTER this, so its matrices enumerate the ruled
  grammar.
- LANGUAGE_SPEC.md + saw-lang skill + README per design 125.
