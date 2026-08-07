# Design 174 — investigation: the T = U? sweep

**Status: APPROVED (user, Aug 7: "we should do a sweep for other cases where
generic T defined as Type? might cause issues"). PROBE-ONLY investigation —
no compiler changes; the product is findings. Findings feed the
places/optional plumbing batch (DF-146j/l/m/n/o, already decided) or file as
their own DF-174x. Concurrent-safe with every running agent (scratch probes +
tracker append only).**

## Why

Instantiating a generic at an Optional (T = U?) exercises every piece of
machinery that treats Optionals specially — auto-wrap, None literal typing,
payload-read places, chaining — through a path the special cases may not
cover. One afternoon of ad-hoc probing found three: DF-146l (None literal
ICEs in a Map literal and as a `??` RHS), DF-146m (call-site auto-wrap skips
a generic param instantiated to `Int?`), and the (working, verified) honest
`U??` nesting. A deliberate matrix will find the rest.

## The matrix (probe each; record works / clean-error / wrong-behavior / ICE)

1. **Containers of U?**: Vector<Int?> (push/get/[]/set/iter/for-in/pop/
   swap_out/with_ref), Map<K, Int?> (insert/[]/keys/values/each),
   Set<Int?> (is Optional Hashable? expect a clean error — verify it IS
   clean), Map<Int?, V> KEYS (same question), literals of each incl. None
   elements (the DF-146l class), `[None; 4]` repeat literal.
2. **Optional-of-Optional direct**: Int?? construction, `!`/`!!`, take() on
   the outer/inner, `??` at each layer, if let/guard let peeling, match arms,
   whole-binding copy-tier behavior (Int?? is trivial; String?? retains).
3. **Generic functions**: inference from a None argument (`f(None)` — what
   does T solve to? underdetermined error expected — verify clean), explicit
   f<Int?>(None), default values `b: T = None`?, later-arg fixpoint where an
   earlier arg is None, RETURN-position auto-wrap in `-> T?` at T = Int?
   (does `return 42` wrap once or twice — and which is right?), Result
   auto-wrap with Ok(T) at T = Int?.
4. **Concurrency**: Channel<Int?> send/receive shapes (does the closed-
   channel signal collide with a None VALUE anywhere in the surface?),
   TaskGroup spawn of a task returning Int? + join, an Int?? frame local
   held ACROSS A SUSPEND (coro frame slot typing), Arc<Int?> +
   with_unique, Mutex<Int?>.lock body param.
5. **Places**: v[i] windows on Vector<Int?> (verified working — pin it as a
   test), m[k]!.take() through the window, place value reads at each tier
   (Int?? vs String?? vs Vector<Int>? element).
6. **Formatting/traits**: print/"{}" of Int?? (Printable of Optional?),
   equality Int?? == Int?? (Equatable of Optional?), Optional as a generic
   BOUND satisfier (does Int? satisfy `T: Equatable` where Int does?).
7. **try_ tier**: try_push(None) on Vector<Int?>, Result<Int?, E> consumed
   via try/try!.

## Deliverables

- `examples/`-grade pin tests for everything that WORKS (the honest-U??
  behaviors become permanent regression tests — suggest examples/
  optional_generic_*.saw, committed with EXPECT directives).
- Tracker findings for everything that doesn't: extend DF-146l's trigger
  list rather than new numbers where it is the same root; new DF-174x
  otherwise; wrong-behavior (not ICE) findings marked P0.
- A summary table in this brief (works / error-quality / broken) as the
  investigation report.

## Rules

Probes under .build/scratch/ first; promote to examples/ only what passes
and pins real behavior (with EXPECT directives; suite must stay green —
run the full suite before committing test promotions). No compiler edits —
even obvious one-liners get filed, not fixed (the plumbing batch owns the
fixes; it dispatches after 170 integrates). Standing hygiene rules apply.
