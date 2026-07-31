# Design 73 — Closures become ImplicitCopy (refcounted env) (DECIDED Jul 31)

**Ruling (user):** option D for the design-71 residual gap. An
escaping closure's heap env gains a refcount header; the closure value
joins the **ImplicitCopy** family (String/Arc): every copy is a
refcount bump, the env destructor + free run exactly once when the
last owner drops. This dissolves the closure-in-copyable-struct
double-free entirely and RETIRES design 71's NoCopy/move ceremony at
closure bindings.

## Scope
1. Env layout gains a refcount word (platform word, atomic like
   String's — closures can cross threads via spawn). Retain on copy,
   release-and-dtor-at-zero on drop, through the existing
   retain/release glue family (`_emit_retain_at`/`_emit_drop_at`
   learn the closure case; dtor_ptr still called at zero).
2. Copy class flips: escaping closures classify ImplicitCopy at the
   value-transfer checkpoint (bindings, fields, elements, args,
   returns). `let g = f` is legal again (both valid). Remove design
   71's closure NoCopy binding rejections + the
   `closure_copy_requires_move_error` test (becomes a positive test).
   Capture-less closures (null env) stay trivially copyable (retain
   is a no-op on null env — guard it).
3. Struct containment: the design-71 field exclusion becomes
   CORRECT rather than permissive (an ImplicitCopy field never blocks
   containment); struct copies retain the env. The residual-gap test
   shape (owning closure in copyable struct, struct copied) becomes a
   positive exact-count test: dtor once, at last drop.
4. Spawn/trampoline + TaskGroup frames: retain/release balance across
   the thread boundary (frame owns a +1; trampoline release is THE
   release — exactly-once tests). Design-71's drop-order tests
   updated: destructor now runs at the LAST owner's drop (LIFO of the
   final owner).
5. Sharing semantics note for the spec: captures are moved IN at
   creation; copies share the (immutable) env — there is no
   observable mutation through an env, so sharing is semantically
   invisible. `[&var x]` reference-captures remain non-escaping-only
   (unchanged).
6. Docs: spec closures section rewritten (ImplicitCopy, refcounted
   env, exactly-once teardown), saw-lang skill Copy-tier table +
   gotcha, tracker (design-71 residual gap CLOSED, design 73 landed).

## Tests
Exact-count battery (Arc/Deinit probes): copy binding + both call;
struct-with-closure copied N times → dtor once; closure in Vector
copied; passed by value; returned; spawn (thread) + TaskGroup spawn
balance; capture-less closure null-env fast path; conditional-move
shapes from 71 still exactly-once; drop-order updated.

Bars: full suite (baseline 803) + blade/libs + bootstrap green per
commit; zero xfails. Standing policy applies.
