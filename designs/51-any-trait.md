# Design 51 — `any Trait` existentials (D16, DECIDED Jul 29)

**Ruling (user):** ship user-facing dynamic dispatch NOW as `any Trait`
— not an internal-only vtable. Keyword `any` (Swift's modern spelling;
names the intent, full-word style; leaves the opaque-type counterpart
open). Opaque/static-dispatch sugar is PUNTED; when it comes, the
provisional keyword is **`generic`** (user preference — honest about
the mechanism; recorded nuance: in return position opaque types are
reverse generics, not plain sugar, though still monomorphized
underneath). Erased values live only behind explicit ownership — no
Swift-style hidden existential container, per costs-visible.

## Decided semantics (v1 scope)
- `any Trait` as a CONTEXTUAL keyword in type position (the
  sync/escaping pattern; `any` stays valid as an identifier).
- Unsized discipline: legal ONLY as `&any Trait` (borrowed parameter —
  non-escaping as all references) and `Box<any Trait, A = Global>`
  (owned, NoCopy — falls out of Box). Anywhere else (bare binding,
  field, by-value param/return): clean error naming the rule.
  `Vector<Box<any Trait>>` composes for heterogeneous collections.
  `Arc<any Trait>` DEFERRED (note in tracker when landing).
- **Erasure happens at construction/call boundaries only** (no
  Rust-style retroactive unsizing coercion): `&circle` passed where
  `&any Shape` is expected attaches the vtable; `Box<any Shape>`
  is built erased-directly via the Box factory taking the concrete
  value (`Box<any Shape>.make(move circle)` — surface per brief-42's
  factory pattern; report the exact spelling chosen).
- Representation: fat pointer (data ptr, vtable ptr). Vtable per
  (concrete type, trait) conformance, emitted from the statically-known
  extension declarations: [destructor = __deinit_in_place glue, size,
  align, method fn-pointers in trait declaration order]. Const static
  data (rodata; freestanding-fine).
- Dispatch: `x.method(args)` on an `any` value → vtable slot indirect
  call, `self` = data pointer. Effects: the call carries the TRAIT
  signature's declared effect (`sync` trait methods stay sync-callable
  through `any`; unmarked = conservatively suspending — consistent
  with function-type rules).
- **Object safety (v1 = not-any-able, clean diagnostics naming why):**
  traits with Self-by-value params/returns (the whole Copy family),
  traits with generic methods (brief 36), traits with associated types
  (Iterator — pinning syntax `any Iterator<Item = Int>` is a later
  addition). Marker traits (Send/Sync/NoCopy...) are not dispatchable
  — any-ing them is an error (nothing to call).
- `Box<any Trait, A>` teardown: destructor + size + align from the
  VTABLE (not sizeof<T>); dealloc routed to A with vtable size/align.
  Exactly-once payload deinit through erasure (deinit-oracle tests).

## Items
1. Parser (contextual `any` in type position) + SawType EXISTENTIAL
   kind + display.
2. Object-safety checker + the unsized-discipline rejections.
3. Vtable synthesis + emission (per conformance, on demand at first
   erasure site of the (type, trait) pair — lazy like
   monomorphization, via the pending queue).
4. Coercion at call boundaries (&T → &any Trait) + erased Box
   construction; method dispatch codegen through the fat pointer.
5. Box teardown via vtable (deinit-oracle: String payload, Deinit
   struct payload, exactly once, -O0 spot checks).
6. Tests: heterogeneous Vector<Box<any Shape>> render loop (the spec's
   own motivating sketch); &any param polymorphic call; every
   object-safety rejection; unsized-discipline rejections; effect
   propagation (sync trait method through any inside a sync context —
   accepted; unmarked — rejected); slab-allocated Box<any T, SlabA>
   erased teardown.
7. Docs: LANGUAGE_SPEC traits section (any, object safety, the
   explicit-ownership rule, no-hidden-container divergence from
   Swift); CLAUDE.md; spec keyword appendix (`dyn` reservation
   RETIRED in favor of `any`; note `generic` as the provisional
   future opaque keyword).

## Hazards
Vtable/mangling interplay (the canonical mangler names the vtable
symbols); deinit-through-erasure is the double-free-class risk —
deinit/string/implicit_copy families at every checkpoint. The
brief-45 executor consumer (A1b) lands SEPARATELY after this — do not
build executor machinery here, but keep `trait Resumable`-shaped
usage in mind (a &var-self method trait must be any-able: verify
&var self methods pass object safety — they must; only Self-BY-VALUE
is excluded).
