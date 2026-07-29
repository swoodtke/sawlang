# Design 46 — UnsafeMemory<T, Use>: typed memory at fixed addresses (D12, DECIDED Jul 29)

**Ruling (user, refined through discussion):** one family type,
`UnsafeMemory<T, Use>`, for typed access to memory at a fixed address —
register blocks AND board bootstrap regions (initial stack, early
heap). The `Use` parameter is an **intent marker** consumed per layer:
the compiler derives access discipline from it (mechanically
guaranteed); platform setup derives its configuration obligations from
it (a visible responsibility, not a type-level promise — cache
attributes live in PMAs/page tables/cache controllers, which boot code
configures; the declaration is the coordination point). Also ratified
en route: the **Unsafe-prefix house rule** — any type whose ordinary
use can violate memory safety carries the prefix (UnsafePointer family,
UnsafeMemory, the future UnsafeCell-equivalent).

## Decided semantics
- `UnsafeMemory<T, Use>` — compiler-known, one word (the address),
  const-init from an integer literal, static-able, Sync by fiat
  (Atomic precedent). **`Use` is explicit always** — no default
  (fail-direction: forgetting Device = silently elidable MMIO;
  forgetting Normal = merely slow; with no default neither is
  forgettable).
- **`Device` intent** (register blocks): compiler emits volatile
  loads/stores; `read()`/`write(v)` on scalar-typed views ONLY — no
  whole-struct access (multi-register access is never atomic; reads
  have side effects); `ReadOnly<T>`/`WriteOnly<T>` layout-transparent
  field markers gate which accessor projection exposes (plain field =
  RW). Volatile ≠ atomic — documented.
- **`Normal` intent** (bootstrap/DMA-visible RAM regions): plain
  loads/stores; whole-struct/element access allowed; region accessors
  `ptr() -> UnsafePointer<Int8>`, `len()`, `end()` (stack-top / slab
  handoff: `slab_init(EARLY_HEAP.ptr(), EARLY_HEAP.len(), ...)`).
- **Projection (both intents, one shared engine):** member access on
  `UnsafeMemory<Struct, U>` yields `UnsafeMemory<Field, U>` at base +
  compile-time offset (no memory touched); chains through nested
  structs; index projection through fixed-array fields.
- Layout guarantee: declaration-order natural ABI layout (documented);
  `_pad` reserved fields as the interim idiom; repr/explicit-offset
  attributes deferred until a device demands them.
- Safety: address fabrication is UnsafePointer-trust-bucket (unsafe
  blocks remain deferred; the naming convention is the marker).
- Future hooks (noted, not built): compile-time reflection over a
  board module's UnsafeMemory statics generating PMP/cache setup;
  additional intent markers only when compiler-expressible behavior
  earns them (e.g. non-temporal streaming); **fence/barrier primitives
  are a separate tracker item** (DMA ordering: write RAM → fence →
  ring doorbell — intent markers do not remove the need).

## Example (the board-module idiom)
```saw
struct UartRegs {
    data:   UInt32,
    status: ReadOnly<UInt32>,
    ctrl:   UInt32,
    intclr: WriteOnly<UInt32>,
}

static UART1:      UnsafeMemory<UartRegs, Device>        = UnsafeMemory(0x18003000)
static BOOT_STACK: UnsafeMemory<[UInt8; 16384], Normal>  = UnsafeMemory(0x3FC7C000)
static EARLY_HEAP: UnsafeMemory<[UInt8; 65536], Normal>  = UnsafeMemory(0x3FC80000)

while UART1.status.read() & TX_FULL != 0 { }   // needs T1a bitwise ops
UART1.data.write(byte)
let sp = BOOT_STACK.end()
```

## Implementation items
1. Compiler-known type + const-init + statics + Sync fiat (mirror the
   brief-41 Atomic machinery); Device/Normal/ReadOnly/WriteOnly marker
   types.
2. Shared projection engine (field offsets via llvmlite target data —
   the alignof plumbing has the pieces); array-index projection;
   intent/marker gating diagnostics (Device whole-struct → error;
   RO write / WO read → error; Normal gets whole ops + ptr/len/end).
3. Access codegen: volatile flags on Device loads/stores; verify via
   --emit-ir that Device accesses are marked volatile and a
   read-twice test keeps both loads at O1; Normal emits plain access.
4. Tests: scalar rw both intents; register-block projection incl.
   nested + array; RO/WO gating errors; Device whole-struct error;
   static instances; the not-elided IR check; hosted MMIO simulation
   via a static byte array aliased through both a Normal view and
   direct access (offset math verified observably); region accessors.
5. Docs: LANGUAGE_SPEC unsafe/FFI section (the model, per-layer intent
   semantics, naming rule, volatile≠atomic, layout guarantee);
   CLAUDE.md.

## Hazards
Volatile flags must survive the O1 pipeline (IR test is the oracle).
Projection must never load the aggregate. The hosted simulation must
use the same address arithmetic as real use.
