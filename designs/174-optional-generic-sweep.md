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

---

# Investigation report (Aug 7, probe-only)

## Headline: no SILENT wrong behavior exists in this matrix

The sweep looked hardest for the P0 class — a `T = U?` instantiation that
compiles and then quietly does the wrong thing. **It found none.** Every
break is loud: a parse error, a clean type error, an ICE, or (once) a
malformed-IR crash. The two properties that would have been silent if wrong
were both checked directly and are both correct:

- **Drop counts.** `Vector<Res?>` and `Map<String, Res?>` over a NoCopy
  payload deinit each `Some` exactly once and each `None` not at all; an
  ImplicitCopy payload read out of an optional element is a real retain that
  outlives the container. No leak, no double free.
  (`examples/optional_generic_ownership.saw`)
- **Discriminant-aware hashing.** `Set<Int?>` and `Map<Int?, V>` keep `None`
  and `0` DISTINCT — dedup, `contains`, and `remove` all agree. A collision
  here would have been undiagnosable data loss.
  (`examples/optional_generic_hashable_keys.saw`)

The brief expected `Set<Int?>` to be a clean REFUSAL and asked that the
refusal be verified clean. The real answer is better: it works, correctly.

The highest-severity finding is **DF-174a**, and its severity is that the
LLVM verifier is the only thing catching it — a skipped return auto-wrap
that, uncaught, would be a type-confused read.

## Matrix verdict table

| # | Area | Probe | Verdict | xfail-pinned |
|---|------|-------|---------|--------------|
| 1 | `Vector<Int?>` | push/get/`[]`/set/iter/for-in/pop/swap_out/with_ref/each/map/fold | **works** — `get`/`pop` yield an honest `Int??` | — |
| 1 | `Vector<Int?>` | literal with a bare `None` element | **works** | — |
| 1 | `Vector<Int?>` | repeat literal `[n; 4]` and `[None; 4]` | **works** | — |
| 1 | `Map<String, Int?>` | insert/`[]`/get/contains_key/values/each/each_value/remove | **works** — `[]`/`remove` yield an honest `Int??` | — |
| 1 | `Map<String, Int?>` | Map LITERAL with a `None` value | **ICE** (DF-146l site 1) | `optional_generic_none_map_literal_xfail` |
| 1 | `Map<String, Int?>` | `m.insert("y", 7)` — auto-wrap at a generic param | **clean error, wrong outcome** (DF-146m) | `optional_generic_insert_autowrap_xfail` |
| 1 | `Set<Int?>` | insert/contains/remove; `None` vs `0` | **works** — discriminant hashed | — |
| 1 | `Map<Int?, V>` | Optional KEYS; `None` vs `0` | **works** | — |
| 2 | `Int??` direct | naming the type: `Int??`, `Optional<Int?>`, `(Int?)?` | **no spelling exists** (DF-174c) | `optional_generic_nested_spelling_xfail` |
| 2 | `Int??` direct | `if let` peeling, `??` per layer, `take()` on either layer | **works** (reached via instantiation) | — |
| 3 | generics | explicit `f<Int?>(None)`, `f<Int?>(v)` | **works** | — |
| 3 | generics | `-> T?` with `return x` at `T = Int?` | **works** — wraps exactly once | — |
| 3 | generics | `-> T?` with a TAIL expression | **malformed LLVM IR / crash** (DF-174a) | `optional_generic_return_tail_xfail` |
| 3 | generics | `f(None)` — inference from a bare None | **ICE** (DF-146l site 3, NEW) | `optional_generic_none_generic_arg_xfail` |
| 3 | generics | `b: T = None` default value | **ICE** (DF-146l site 4, NEW) | `optional_generic_none_default_value_xfail` |
| 3 | generics | later-arg fixpoint `pick(None, some)` | **poor error, wrong rejection** (DF-174f) | `optional_generic_infer_later_arg_xfail` |
| 3 | generics | `Result<Int?, E>` auto-wrap + `try!` | **works** | — |
| 4 | concurrency | `Channel<Int?>` `receive`/`try_receive` — None VALUE vs empty | **works** — the two are distinct, no collision | — |
| 4 | concurrency | `TaskGroup.spawn` of a task returning `Int?` | **ICE** (DF-174b) | `optional_generic_spawn_result_xfail` |
| 4 | concurrency | `Int??` local held across a suspend | **works** — both layers survive the frame slot | — |
| 4 | concurrency | `Arc<Int?>` + `with_unique`, `Mutex<Int?>.lock` | **works** | — |
| 5 | places | `v[i]` read, `v[i] = 9`, `v[i] = None`, `g[0]!.n += 1`, `m[k]!` read | **works** | — |
| 5 | places | `v[i] = <an Int? value>` | **wrong error text + capability gap** (DF-174e) | `optional_generic_place_assign_xfail` |
| 5 | places | `m[k]! = v` whole-value replace | **parse error** (DF-146n, decided) | `optional_generic_map_force_assign_xfail` |
| 5 | places | `m[k]?.field = v` chain-assign with a place head | **clean error** (DF-146o, decided) | `optional_generic_chain_assign_place_head_xfail` |
| 5 | places | value reads per tier: `Int?`, `String?`, struct payload | **works** | — |
| 6 | traits | `Int? == Int?`; `T: Equatable` satisfied by `Int?` | **works** — `None == None`, `Some != None` | — |
| 6 | traits | `print`/`"{}"` of an Optional | **clean error, poor hint** (DF-174d) | — |
| 7 | try_ tier | `try_push(None)` / `try_push(some)` on `Vector<Int?>` | **works** | — |
| 7 | try_ tier | `Result<Int?, E>` via `try!` and `match` | **works** | — |

Tally: **21 behaviors work**, 4 ICE, 1 malformed IR, 1 parse error, 4
clean-or-poor errors that should not be errors.

## Findings

### New — filed as DF-174a..f

- **DF-174a (highest severity).** A generic function returning `T?` skips the
  return auto-wrap for a TAIL EXPRESSION and emits malformed LLVM IR
  (`ret i64` into a `{ i1, i64 }` result). NOT Optional-specific — it
  reproduces at `T = Int`. The `return x` spelling and the non-generic
  `func w(x: Int) -> Int? { x }` are both correct.
- **DF-174b.** `TaskGroup.spawn` of a task whose result type is an Optional
  ICEs: the result cell is typed one Optional layer deeper than the value
  stored into it.
- **DF-174c.** A nested optional type has NO SPELLING, so the two-layer values
  the containers genuinely produce cannot be named — no helper can take one.
- **DF-174d.** `Optional<T>` was never wired up as a writable type name, and
  more broadly a bare UNKNOWN type name produces no diagnostic at all.
- **DF-174e.** `v[i] = <a T? value>` on a `Vector<T?>` is refused with an error
  naming the wrong element type; `set` accepts the same value.
- **DF-174f.** Later-arg inference will not unify a bare `None` with the
  Optional a later argument fixes.

### Extended — DF-146l gains two trigger sites

Sites 1 (Map literal value) and 2 (`??` RHS) reproduce as filed. This sweep
adds **site 3: a bare `None` as a GENERIC CALL ARGUMENT** and **site 4: a
`None` DEFAULT VALUE typed by a type parameter**. All four die with the same
`None literal has no type information` ICE.

### Verified as filed, not re-filed

DF-146m, DF-146n, DF-146o, and the honest `U??` nesting (now pinned as a
permanent regression test rather than a probe).

## Deliverables

19 tests under `examples/optional_generic_*.saw` — **7 pin tests** for
verified-working behavior, **12 XFAIL tests** for the broken cases (each the
minimal repro, with EXPECT directives stating the POST-FIX behavior so the
XPASS flip validates the fix). Suite green: 7 passed, 12 xfailed.
