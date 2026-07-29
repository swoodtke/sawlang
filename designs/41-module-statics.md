# Design Brief 41 — Module-level statics (+ Atomic<Int>) and the UInt division fix

**Source:** tracker F4, under the ALREADY-DECIDED statics semantics
(design 19 open-questions block, user-ratified): statics are
**Sync-only, const-initialized, immortal (never deinit), and there is
NO `static mut`, ever** — mutation of global state flows only through
interior-synchronized types. Also picks up L13 (the xfail-ledgered UInt
division bug) as an opening item since it's small and wrong-result.
**Exit criteria:** statics usable per the decided semantics with tests;
a minimal `Atomic<Int>` lands (named in the decision as an
interior-synchronized primitive; prerequisite for brief 42's slab);
`uint_division_signedness` xfail flips; full suite green; zero xfails.

## Items

### 0. (L13) UInt division/modulo signedness
`/` and `%` always emit `sdiv`/`srem`; UInt operands with the high bit
set compute wrong results. Pick udiv/urem (and the div-overflow check
only for signed) by the same signedness resolution the overflow
intrinsics use (`_int_is_signed`, brief 31). Flip the xfail (remove
marker); add a UInt modulo case.

### 1. `static` declarations
`static NAME: Type = initializer` (and `public static`) at module top
level. Parser + AST + registration (namespace symbol kind). Name
resolution: statics are readable like immutable bindings wherever
visible (module-local by default; `public` exports; module-qualified
access `mod.NAME` works).

### 2. The decided constraints, enforced
- **Const-init only:** initializer must be a compile-time constant —
  literals, POD struct literals with constant fields, fixed-array
  literals of constants. PROBE whether a repeat-literal (`[0; 4096]`)
  exists; if not, support bare-declaration zero-init for POD/array
  statics (`static BUF: [Int8; 4096]` → zeroinitializer) since slab
  regions need large zero arrays — pick one and document. Anything
  else (function calls, String, heap types): clean error.
- **Sync-only:** the static's type must be Sync (structural derivation
  from brief 21). Non-Sync type → error naming the type.
- **No mutation:** assignment to a static (whole, field, or element)
  is a compile error ("statics are immutable; use an
  interior-synchronized type"); `&var STATIC` as a call argument
  likewise. `&STATIC` immutable lends are fine.
- **Immortal:** no deinit registration ever (const-init restricts to
  non-Deinit types in practice anyway — assert, don't build glue).

### 3. Codegen
LLVM module globals: constant globals for immutable POD statics
(rodata-eligible), non-constant only for interior-mutable cases (item
4's Atomic). Reads load through the global. Works under
`--freestanding` (globals land in .data/.rodata/.bss with no libc) —
verify with a cross-triple object emission probe like brief 20's.

### 4. Minimal `Atomic<Int>`
Compiler-known struct (like String's refcount treatment): Sync by fiat,
const-initializable from an Int literal (`static N: Atomic<Int> =
Atomic(0)`), methods `load()`, `store(v)`, `fetch_add(v) -> Int` (old
value), `compare_exchange(expected, desired) -> Bool` — lowering to
LLVM atomic ops (seq_cst; the String refcount protocol's orderings as
precedent). Usable in statics AND as struct fields. Mutating methods
work through the static (interior mutability — this is the ONE
sanctioned mutation path; make sure the item-2 no-mutation rule keys on
assignment, not method calls). Tests: static counter incremented from
main; a two-thread spawn test racing fetch_add to a deterministic sum
(the concurrency machinery exists — briefs 21/21b).

### 5. Tests & docs
Success: POD static, array static, public static cross-module, Atomic
static counter, threaded Atomic. Errors: non-const init, non-Sync
type, assignment (whole/field/element), `&var` lend, `static` inside a
function (parse error or clean diagnostic — pick). Docs:
LANGUAGE_SPEC.md statics section (the decided rules, verbatim
semantics), CLAUDE.md bullet. Annotate design 19's statics decision as
LANDED.

## Hazards
Codegen globals interact with the module merge (one LLVM module) —
name-collision handling for same-named statics in two modules follows
brief 26's identity/collision rules (test it). The no-mutation rule
must not break interior-mutable method calls (Atomic) — that
distinction is the crux of the decided model. Full suite per commit.

## Report back
Per item: mechanism + verification. Item 2's repeat-literal/zero-init
choice. Item 4's ordering choices. The cross-module static collision
behavior. Suite tally; deviations; non-allowlisted commands.
