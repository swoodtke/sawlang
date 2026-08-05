# Design 81 — Unsafe surface: `unsafe` marker + escape rules + with_ref (DECIDED Jul 31)

> **SUPERSEDED by design 130 (Aug 5) — the MARKING rules only.** The line-level
> `unsafe` expression marker, the "invisible flow" test that decided where it
> was required, and the marked-domain escapes (a pointer-carrying signature, a
> `self`-method of a pointer-field struct, a pointer-naming cast) are all gone
> from the language. Marking is now per-DECLARATION: `unsafe struct` for a type,
> `unsafe func`/`unsafe init` for a function that names, binds, receives or
> returns one of its values. Writing the old expression marker is a parse error.
>
> Design 81's other two rulings STAND: unsafety is type-carried rather than
> region-carried (still no `unsafe` blocks), and `Vector.with_ref`/`with_var_ref`
> remain the only container borrow-projection model, with `ref_at` removed.
>
> Why it changed: the marker was too coarse inside pointer-holding types
> (`vector.saw` carried 2 markers in ~530 lines because the whole type was
> blanket-marked, so nothing distinguished sound `pop` from overflowing `push`)
> and nothing stopped an unsafe operation from being re-exported through a safe
> signature (`String.byte_at` marked its `unsafe ptr[index]` correctly and the
> out-of-bounds read bug happened anyway). See `designs/130-unsafe-model.md`.

**Ruling (user):** the type-carried principle gains a VISIBILITY rule:
where an `Unsafe*` type appears in source (signature, field decl) it
is allowed; where an unsafe value would flow INVISIBLY, the reserved
`unsafe` keyword is required at that exact site. Scoped closures
(`with_ref`) become the ONLY container borrow-projection model —
`ref_at` is REMOVED.

## The rules (pinned with the user)
- Parameter of Unsafe* type: free (like `&T` — signature visible).
- Argument passing an Unsafe* value through a call: free (like `&x`).
- Struct FIELD of Unsafe* type: allowed — the typed field decl is the
  visible marker.
- RETURN type carrying Unsafe*: allowed at the declaration…
- …but BINDING a pointer-producing expression requires the marker:
  `let p = unsafe A().alloc(size, align)`.
- Deref/index/write/pointer-arith in a function whose OWN signature
  carries no Unsafe* type: requires `unsafe` on the expression
  (`unsafe ptr[0] = 65`).
- Inside a function whose own signature carries Unsafe* types: free —
  already the marked domain.
- Net: SAFE code has exactly reference semantics for pointers (pass-
  through only); every entry to the unsafe domain is greppable via a
  signature, a field type, or the `unsafe` keyword.

## Scope
1. `unsafe` keyword un-reserved into an expression-prefix marker;
   typechecker enforcement of the table above (one chokepoint that
   classifies each Unsafe*-involving expression by context). Clean
   errors: "binding an UnsafePointer requires `unsafe`" etc., with
   the marked-domain explanation. `unsafe` on an expression with no
   Unsafe* involvement = warning-free no-op? NO — make it an ERROR
   ("nothing unsafe here") to keep markers honest.
2. **`Vector.with_ref(i, body: (&T) -> Void)`** (+ `with_var_ref` for
   `&var T`, non-escaping, exclusivity holds the vector borrowed for
   the body — iterator-invalidation-proof) as THE projection API;
   same for Map value access if a use case exists (report).
   **REMOVE `ref_at`** and migrate its users (std + any tests).
   Multi-element patterns get index-based code or a with_two_refs if
   a real site demands it (report, don't speculate).
3. Std/FFI sweep: add `unsafe` markers where the new rules demand
   (slab, Box.make, net.saw buffer casts, String withCString
   internals, UnsafeMemory accessor uses in examples); the sweep IS
   the audit — report every site that was silently binding pointers.
4. UnsafeMemory: its methods stay the MMIO model (Device read/write
   are its own contract); binding an UnsafeMemory VALUE is a static
   const-init (design 46) — unchanged; but its `ptr()`/region
   accessors now fall under the binding rule like any pointer
   producer.
5. Coroutine/frames: synthesized frame code (`__recv` pointers etc.)
   is compiler-generated — EXEMPT by provenance (same discipline as
   design 80's synthesized-access exemption).
6. Tests: each rule row (allowed + rejected forms), the marker-on-
   nothing error, with_ref/with_var_ref (incl. mutation through it +
   exclusivity violation attempt = compile error + invalidation
   attempt inside body = compile error), ref_at gone (unknown-method
   error), migrated std green. Spec: rewrite the Unsafe Code section
   (the principle + the visibility rule + the table); saw-lang skill
   (unsafe section rewritten — with_ref is the blessed pattern);
   CLAUDE.md digest; tracker.

## Hazards
- The enforcement chokepoint must not double-fire through DF3 wrap /
  labeled-arg binding / overload paths — one classification pass on
  the RESOLVED callee (design 55 chokepoint discipline).
- with_ref bodies interact with the closure machinery (non-escaping,
  design 29) and the design-73 refcount work — the borrow must not
  retain (it's a lend); exact-count tests.
- Marker placement in the grammar: `unsafe <expr>` binds tighter than
  assignment, looser than postfix — pin precedence with tests
  (`unsafe p[0] = 5` marks the whole store).
Full suite + blade/libs + bootstrap green per commit; zero xfails.
Standing policy; interruption-safe commits; load + self-review
against the saw-lang skill.
