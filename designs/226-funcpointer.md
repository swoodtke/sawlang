# Design 226 — `FuncPointer<F>`: a typed function pointer, not first-class functions

**Status: RULED (user, Aug 15 — direction + name + the safe-type
re-ruling; formalized from the tracker entry Aug 16). Ready to
dispatch. COMPILER SCOPE ONLY — the kernel-side adoption defers to
M3 (see "Deferred" below).**

## What this is, and is not

The DF-178c fix: entry points and C callbacks get a TYPED function
pointer, WITHOUT making functions first-class values (that stays
DF-172a's open question). `F` is a function TYPE carrying the effect
slot — **sync only**: a suspending body needs a frame a bare pointer
cannot carry, so a suspending `F` is a clean error at the type.

## The safe-type ruling (re-ruled Aug 15, supersedes the first pass)

`struct FuncPointer<F>` is a **SAFE type**. Under closed construction
every inhabitant is verified code of signature `F`, so possession and
the indirect CALL are sound for every input — design 130's rule
satisfied, and code is immortal, so no dangling exists. APIs receiving
one need no `unsafe` declaration. Unsafety is confined to the ONE
forging member:

```saw
FuncPointer<F>.from_raw(addr) unsafe -> FuncPointer<F>
```

— unsafe automatically by 130's trigger rule (it binds a raw
address); for C-callback pointers arriving from FFI and loaders
reading entry PCs. The Vector precedent applied properly: the type is
safe, the one member reaching through is not.

NOTE for the implementer: the original tracker entry twice spells
`UnsafeFuncPointer` — both are STALE pre-re-ruling text. The type is
`FuncPointer<F>`, safe, and the design-130 `Unsafe*` naming rule would
in fact forbid the stale spelling on a safe struct.

## Construction (two forms, both ruled)

1. **A ZERO-CAPTURE closure literal COERCES in FuncPointer-expected
   position.** Its body is emitted under `F`'s bare ABI — no env
   parameter (the Rust non-capturing-coercion precedent) — zero-alloc
   by construction, no overload ambiguity, `F` inferred from context.
   ANY capture refuses — INCLUDING implicit ones (`self`, enclosing
   locals; the DF-216a lesson: count what the body NAMES, not what
   the capture list writes) — with a teaching diagnostic ("pass state
   through the argument parameter").
2. **A named, unambiguous, non-generic function.** An overload set
   larger than one demands annotation to select; generic functions
   refused in v1.

Calling one is an ordinary call expression on the value; the call is
safe (the soundness argument above).

## Units

1. **The type + typechecker surface.** `FuncPointer<F>` declared
   (std or builtin per where function types already live), `F`
   validated (function type, sync, and the design-136 rule: `F`
   carrying `unsafe` iff its signature names an unsafe type — the
   existing function-type check reused, not copied). `from_raw` with
   its automatic unsafe marking. Copy tier: trivial (a code address —
   bitwise copy is correct). Send/Sync: derives (code is immortal and
   stateless).
2. **The two construction forms.** The zero-capture coercion (the
   capture check is a FUNNEL shared with the existing escaping-
   capture analysis — obligation 1: one body-names walk, its
   docstring naming both consumers) + the named-function form with
   the overload/generic refusals. Position matrix for the coercion:
   argument, `let` with annotation, struct field init, return, static
   init — each a test, plus the capture-refusal tests (explicit
   capture, implicit `self`, implicit enclosing local).
3. **Codegen + the call path.** The bare-ABI emission for coerced
   literals (one synthesized symbol per literal), the indirect call,
   and a hosted FFI round-trip test: a C function taking a callback
   (via the existing extern machinery) invoked with a
   `FuncPointer` built from each construction form.
4. **Docs**: LANGUAGE_SPEC (new section + the DF-178c/172a
   cross-references), saw-lang skill, README per convention.

## Deferred (explicitly)

- **Kernel adoption** — `create_thread(entry: FuncPointer<(UInt) sync
  -> Never>, ...)` replacing the M2 image-entry stub, with the kernel
  STILL range-checking the entry PC against the RX grant and faulting
  (raw-ecall bypass defense: boundary checks and type safety each do
  their own job). This lands with M3 UNIT 2 (CreateProcess reworks
  that exact surface — designs/232) under SOS review policy, not
  here.
- First-class functions generally (DF-172a stays open).
- Generic named functions as construction sources (v1 refusal).

Obligation notes: 2 — no existing contract flips (new surface; the
zero-capture coercion changes no existing closure's meaning, since a
FuncPointer-expected position does not exist in any current program);
3 — the safe-type soundness argument IS a safety surface: a
conformance row asserting the capture refusal (the property that
keeps the bare ABI sound) is unit 2's first test, INDEX.md row added.
