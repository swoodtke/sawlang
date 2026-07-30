# Design 58 — Attribute grammar + C-callable exports (N6, DECIDED Jul 29)

**Ruling (user):** attributes are **Swift-style `@name` / `@name(args)`**
(the spec's `#[...]` placeholder examples get rewritten); C export is
the **unified `@export`** (one attribute = C calling convention +
unmangled-or-given symbol + survives DCE — no separate
no_mangle/c_abi pieces); **no repr(C) attribute** — the existing
declaration-order natural-ABI layout guarantee (design 46) is
documented as THE struct layout rule, and export signatures are
gated by a type whitelist instead. v1 attribute set: `@export`
(functions + statics), `@section` (functions + statics). `@inline`
deferred (grammar makes it trivial later). Orchestrator note: the
v1-set answer defaulted to the recommended pair; user may adjust.

Unblocks: F7 (kernel entry symbol `_start` / vector table). The boot
shim itself (stack setup) stays assembly — naked functions and inline
asm are OUT of scope; N6 makes Saw functions callable FROM that world.

## Part 1 — attribute grammar
- Lexer: `@` token (currently unused — verify and claim it).
- Parser: zero or more `@name` / `@name(<string-literal>)` lines
  immediately preceding a declaration; attach to the declaration's
  AST node as a list. v1 accepts attributes ONLY on top-level `func`
  and `static` declarations — an attribute on anything else
  (struct/enum/trait/extension/method/local) is a clean error
  ("attributes are not supported on X"), keeping the grammar surface
  honest while leaving room for #[test]/derive-style growth.
- Unknown attribute name = compile error listing the known set.
  Duplicate attribute = error. Argument arity/type checked per
  attribute (`@export` takes zero args or one string literal;
  `@section` requires exactly one string literal).

## Part 2 — @export on functions
- `@export func f(...)` exports with symbol name `f`;
  `@export("sym") func f(...)` exports as `sym`. Semantics (all
  implied, not separable): C calling convention, exact unmangled
  symbol, external linkage, kept alive through DCE/optimization
  (llvm.used or equivalent).
- Restrictions (each a clean compile error):
  - top-level free functions only (no methods, no closures);
  - NOT generic;
  - NOT suspending — the body must be effect-`sync` (cannot suspend
    across a C boundary); check via the existing effect machinery;
  - `public` not required (export is its own visibility to the
    linker) — but note in spec that module visibility still governs
    Saw-side callers.
- **Signature whitelist** (params and return): fixed-width integer
  types (Int8…Int64, UInt8…UInt64), Int/UInt (documented as the
  platform word — matches the C `intptr_t`/`uintptr_t` shape), Float,
  `UnsafePointer<T>`, Void return, and `Never` return (lowered
  noreturn — the `_start` shape). REJECTED in v1 with clean errors:
  Bool (C `_Bool` ABI vs i1 lowering — verify; if the existing extern
  IMPORT path already passes Bool soundly, allow it and report),
  String, Optionals, Results, tuples, closures, and ALL by-value
  structs (by-value aggregate ABI classification is per-target pain;
  pass `UnsafePointer<S>` instead — the layout guarantee makes that
  correct). Report anything the extern-import whitelist already
  handles differently — import and export should end up symmetric.
- Symbol hygiene: two `@export`s resolving to the same symbol =
  error; colliding with a reserved runtime symbol (`saw_*`,
  `__saw_*`, `main`) = error. `@export` + design-55 overloading: an
  exported function's NAME may be overloaded Saw-side, but only ONE
  overload can carry `@export` without an explicit symbol name
  (unmangled symbols can't share a name) — error otherwise.

## Part 3 — @export on statics
- `@export static V: T` / `@export("sym") static V: T`: unmangled
  (or named) external data symbol, kept alive. Same whitelist idea
  for T: fixed-width ints, Int/UInt, Float, arrays thereof, and
  structs of whitelisted fields (data has no calling convention —
  by-value layout IS the guarantee; allowed where function params
  are not). Vector-table idiom must work:
  `@export("_vectors") @section(".vector_table") static VECTORS:
  [UInt32; 64]`.
- Statics are already immortal/Sync-only (design 41) — no new
  lifetime semantics, just symbol naming + liveness.

## Part 4 — @section
- `@section("name")` on top-level funcs and statics: emit the symbol
  into the named object-file section (LLVM section attribute).
  Composes with @export but does not require it. No validation of
  the section name beyond non-empty (linker's problem).

## Part 5 — docs
- Spec: rewrite the planned-C-interop examples (`#[no_mangle]` /
  `#[repr(C)]`, §"C Interop") to the decided @-syntax and current
  reality; document the struct layout guarantee as the language-level
  rule for ALL structs (promote the design-46 note); new Attributes
  section (grammar, the v1 set, the export whitelist, the
  export-vs-overloading rule); keyword/token appendix gets `@`.
- CLAUDE.md current-features; tracker (N6 landed, F7 unblocked).

## Items (suggested commit units)
1. Lexer/parser/AST attribute grammar + position/arity/unknown
   errors + tests.
2. @export functions (codegen: ccc, symbol, used; checker:
   restrictions + whitelist) + tests.
3. @export statics + @section (both targets) + tests.
4. Docs + tracker.

## Tests (minimum)
Grammar: attribute on struct/method/local rejected; unknown attr;
duplicate attr; bad arity. Export funcs: default + renamed symbol
(verify via --emit-ir golden-ish greps in the harness if a C-linked
end-to-end isn't feasible — BUT prefer the in-binary round trip: one
module `@export("saw_bridge_probe") func ...`, another declares
`extern func saw_bridge_probe(...)` and calls it — end-to-end through
the C symbol with no C compiler needed); Never return; generic
rejected; suspending rejected; method rejected; Bool/struct-by-value
rejected (or allowed-with-report per the verify note); duplicate
symbol rejected; `saw_*` collision rejected; overloaded name with one
@export ok / two-unnamed error. Statics: exported data symbol
round-trip via extern static import if supported, else IR check;
vector-table idiom compiles with section+export. Section: IR contains
the section on func and static. Suite stays green (attributes off =
zero behavior change).

## Hazards
- The `used`/DCE-survival path must work at -O1 (default pipeline) —
  test IR at the default opt level, not just -O0.
- Effects: the sync check must run on the exported function like any
  root (it has no Saw caller — make sure effect inference treats it
  as an entry point, same family as `main`).
- The extern-IMPORT machinery already exists (extern blocks in std)
  — reuse its type-lowering decisions so import/export agree on the
  ABI; divergence between the two paths is the classic C-interop bug.
- Parser: `@` must not collide with anything in expression position
  (it's declaration-position only in v1).
Full suite per commit; zero xfails.
