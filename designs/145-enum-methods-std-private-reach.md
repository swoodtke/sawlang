# Design 145 — enum methods + the std private-symbol reach

STATUS: APPROVED (user, Aug 5). Slots right after 141 integrates (user
call — ahead of 135/138/144). Closes DF-140h and DF-140i (filed on the
parked SOS M1 branch's tracker during the round-3 module-system stress;
FILE THEM FRESH in main's tracker as part of landing, noting the origin,
the 142/DF-140f pattern). After this lands on main, the PARKED SOS M1
branch gets a follow-up revision adopting the new capability (unit C
below runs THERE, not on main).

## Unit A — DF-140h: the private-symbol fix reaches std

Design 142's DF-140f fix gave module-private statics and functions
module-qualified codegen symbols — but not in STD modules, so a private
static in a prelude module still reserves its name globally: a user
`static ASCII_ZERO` collides with StringBuilder's private one (5-line
repro, no dependency involved). Extend the same qualification to std
files (design 82 already makes each std file its own module — the
scoping model is there; only the symbol treatment skipped it). NOTE the
distinction 142 drew: std's METHOD-LOOKUP exemption (std as one scoping
domain) is deliberate and STAYS; this unit is about codegen symbol
collisions only. Tests: the ASCII_ZERO repro; a user private static
matching a private static in TWO different std files; the 142 collision
tests unchanged.

## Unit B — DF-140i: enums carry methods

USER enums cannot carry methods today — `extension SysError { func
describe(&self) -> String }` is rejected — so an enum cannot conform to
`Error`/`Printable` with a hand-written body, and every error type in
the tree became a struct to compensate: the language steering authors
off the better-fitting type. (Builtin Optional/Result have methods via
TypeKind machinery — `take()` — the gap is user enums.)

The model — extensions on enums become exactly extensions on structs:
- Instance methods with `&self`/`&var self` receivers; `match self`
  inside bodies is the natural idiom; `&var self` whole-replacement
  (`self = SysError.Other`) per design 110.
- Static methods: yes. `init`: NO — cases are an enum's constructors;
  an init in an enum extension is a clean teaching error.
- Trait conformances with HAND-WRITTEN bodies (`extension SysError:
  Printable { func format(&self, into: &var StringBuilder) {...} }`) —
  the @synthesize derivations already work on enums; hand-written
  override semantics match structs. `Error` conformance follows.
- Generic user enums: methods monomorphize like generic-struct methods
  (design 74 shapes); mangling `Enum_method` joins the existing scheme
  (module-qualified per 142/unit A where private).
- 142's import-scoped lookup and the orphan rule apply unchanged (an
  enum extension is an extension).
- Copy-policy conformances on enums (139) are extensions already —
  verify hand-written deinit bodies inside an enum's policy conformance
  work (131's rule), or record the gap.
Tests: describe-by-match; &var self replacement; static method; init
rejected with the teaching error; Printable enum printed + interpolated;
Error enum through `Result<T, SysErrorLike>` + `try!`; generic enum
method at two instantiations; import-scoped visibility of an enum
extension; @synthesize + hand-written coexistence.

## Unit C — SOS adoption (runs on the PARKED M1 branch afterward)

Once A+B are on main: the M1 branch rebases and `SysError` becomes a
real enum with methods — `Error` + `Printable` conformances replace the
free `sys_error(status)` helper; kernel/root diagnostics format through
it; any other free-function-because-enum shapes in sos/ migrate. The
branch re-parks; the user holds the integration call.

## Gates
Full battery per landing unit on main (suite/lexdiff/irdet/astdiff/
bootstrap/sos); spec (enum + extension sections) + skill (the "errors
are structs" workaround note dies) + README if examples change; tracker:
DF-140h, DF-140i filed-and-closed on main.
