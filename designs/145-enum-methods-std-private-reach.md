# Design 145 — enums stop being second-class: methods, raw backing, and the std private-symbol reach

STATUS: APPROVED (user, Aug 5; unit B2 raw-backed enums folded in with
its three pins confirmed Aug 5). Slots right after 141 integrates (user
call — ahead of 135/138/144). Closes DF-140h and DF-140i (filed on the
parked SOS M1 branch's tracker during the round-3 module-system stress;
FILE THEM FRESH in main's tracker as part of landing, noting the origin,
the 142/DF-140f pattern). After this lands on main, the PARKED SOS M1
branch gets a follow-up revision adopting the new capabilities (unit C
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

## Unit B2 — raw-backed enums [user, three pins confirmed Aug 5]

`enum SysError: UInt8 { case Ok = 0, case BadHandle = 1, ... }` — a
payload-free enum may declare an integer BACKING TYPE in the
declaration's colon position (any fixed-width int or Int/UInt; the
design-47 wire discipline favors fixed-width and docs say so). Semantics:

1. **Payload-free only** — a payload case under a declared backing is a
   teaching error ("an enum with payloads has no integer identity").
2. **Explicit values REQUIRED when a backing is declared** (duplicates
   error; no auto-increment — declaring a backing claims the numbers
   are ABI, so reordering must never silently renumber). Enums WITHOUT
   a backing keep compiler-assigned ordinals and are NOT castable.
3. **Total direction is `as`** (`err as UInt8` — the enum IS its tag);
   **partial direction is a SYNTHESIZED static** `E.from(raw: U) -> E?`,
   None on an unknown value (an invalid wire byte is DATA, never a
   trap). NOT an init — unit B's no-inits rule stands; `from` is a
   lookup, not a constructor.

A declared backing PINS the representation (size and tag values):
backed enums become legal as `UnsafeMemory<T>`-viewed struct FIELD
types (the imgformat `flags` byte can be a typed enum), and are noted
as future `@export`-whitelist candidates (as their backing) — the
C-header story; whitelist admission itself is OUT of this brief.
Equatable/Hashable auto-conformance unchanged; a raw-ordered
Comparable `@synthesize` option is explicitly deferred. Tests: round
trip `as`/`from(raw:)` incl. the None path on an unknown byte; explicit
values enforced (missing + duplicate errors); payload-case-under-backing
error; a backed-enum field inside a static_assert-pinned struct read
through UnsafeMemory; match exhaustiveness unchanged; interaction with
unit B (a backed enum with methods + Printable).

## Unit C — SOS adoption (runs on the PARKED M1 branch afterward)

Once A+B+B2 are on main: the M1 branch rebases and adopts BOTH — 
`SysError` becomes a real backed enum (`: UInt8`, explicit tags) with
methods and `Error` + `Printable` conformances replacing the free
`sys_error(status)` helper; the abi module's op ids and rights bits
become backed enums (`as` at the syscall boundary); imgformat's
`SegFlags` becomes a backed-enum field in the typed header view;
kernel/root diagnostics format through the conformances; any other
free-function-because-enum or static-because-enum shapes in sos/
migrate. The branch re-parks; the user holds the integration call.

## Gates
Full battery per landing unit on main (suite/lexdiff/irdet/astdiff/
bootstrap/sos); spec (enum + extension sections) + skill (the "errors
are structs" workaround note dies) + README if examples change; tracker:
DF-140h, DF-140i filed-and-closed on main.
