# Design 234 — The Fallibility Flip

**Status: RATIFIED Aug 17 2026** (scoped in conversation with the user, all
rulings final). **Queued: dispatches only after the three Aug-17 in-flight
branches integrate** (the kcore split, the literal/const family, the five-item
small-fix batch) — this brief touches std, examples and docs corpus-wide and
would conflict with all of them. M3 unit 1.5+ (sos/kernel-only) may interleave
with units 1-2 at the lead's discretion; the migration units (3+) must not run
beside any other branch.

## The decision

**Every failable operation returns `Result`. Design 123's panic tier is
retired.** Don't hide that things can fail; `try`/`try!`/`try { } catch { }`
are the ergonomics that keep it clean. With it, the alloc `try_` twin family
retires — the census (Aug 17): ~16 twins across nine std files (vector, map,
set, data, stringbuilder, box, arc, channel, alloc): `try_push`, `try_insert`,
`try_append`, `try_reserve`, `try_with_capacity`, `try_make`, `try_set`,
`try_detached`, `try_copy`, `try_append_char`, `try_append_bytes`, `try_send`.
Their behavior becomes the ordinary op's; their names free the `try_` prefix
for its one remaining meaning (§4).

What earned it: the panic tier had grown two families with no handling path at
all in one of them (the hidden allocations), the twins doubled nine API surfaces,
and the `try_` prefix carried two unrelated meanings ("can fail to allocate"
vs "does not block"). The kernel side never lived on the panic tier anyway —
SOS uses slabs, statics, the bump arena, and M3 quotas return statuses — so
the tier was a hosted convenience purchased with a genuinely missing
capability.

## The rulings

### 1. Error-type doctrine: three tiers, no errno enum

- **Leaf ops return the NARROWEST concrete type.** Most std ops have exactly
  one failure mode and need no compound: `push(&var self, v: T) ->
  Result<Void, AllocError>`. `AllocError` keeps its `size`/`align` fields —
  an OOM site stays loggable with context.
- **Compound domain enums, with PAYLOAD-CARRYING cases, only where sources
  genuinely mix.** `ChannelError { Closed, Cancelled, Alloc(e: AllocError) }`;
  `IoError` carries `System(e: SystemError)` at the OS boundary. Never
  re-enumerate the inner vocabulary — carrying the leaf keeps one errno
  caselist in one place.
- **NO stdlib-wide errno-style enum as a return type.** Its defining property
  is that every signature lies: `push -> Result<_, StdError>` claims failure
  modes it cannot produce, and every exhaustive match grows dead arms. errno's
  flatness was C's lack of sum types.
- **`Box<any Error>` is the APPLICATION aggregation tier. std never erases.**
  The erased `Result<T, Box<any Error>>` machinery stays exactly as is, for
  app code that does not care.

### 2. `SystemError` goes public

The runtime-internal `SysError` (rt/'s errno mapping, `enum SysError: UInt8`
in three rt files) becomes the public `SystemError` where a std signature
needs it — the no-abbreviations rule applies the moment it is API. The rt
seam's internal name is untouched by this brief unless a unit finds promoting
one definition cheaper than maintaining two; if promoted, the rename rides.

### 3. Explicit error routing at `try` — `try(as LocalError.Alloc) f(...)`

A `try` site whose callee error type differs from the function's declared
error type SPELLS the routing, as a prefix clause in the `public(package)`
spelling:

```saw
enum LocalError {
    case Alloc(e: AllocError)
    case Parse(line: Int)
}

func build() -> Result<Config, LocalError> {
    let buf = try(as LocalError.Alloc) alloc_buffer(4096)
    let cfg = try(as LocalError.Parse) parse(buf)
    let extra = try read_defaults()          // already LocalError: bare try
    Ok(assemble(cfg, extra))
}
```

- **No auto-lift, no trait, no candidate search.** The named case must have a
  single payload the source error type can fill — checked, done. Benefits
  banked by explicitness: no action-at-a-distance (editing an enum never
  changes behavior at distant try sites), construction sites are greppable,
  zero ambiguity machinery to specify. This is Rust's `.map_err(E::C)?`
  without the closure. Reader-visibility trumps inference — the call-site
  `&var` precedent.
- **PREFIX position is load-bearing, not taste.** A trailing `try f() as X.Y`
  cannot be classified at parse time: `LocalError.Alloc` and `time.Duration`
  are the same dotted-path shape, so the routing clause collides with a
  design-63 value projection of the unwrapped result (`try parse_id() as
  UserId` is legal today and stays so). The prefix slot is owned by `try`;
  every trailing `as` remains an ordinary value cast, unambiguously.
- The clause converts the ERROR CHANNEL only; the Ok value is untouched.
- `try!`/`try?` never take the clause (they do not propagate).
  `try(as …) … catch { }` is refused — route or handle, not both.
- Inside `try { } catch { }` blocks nothing is owed: the catch-site
  synthesized union absorbs every propagated type. The union stays
  UNNAMEABLE — that design holds; the routing clause is the
  signature-crossing mechanism, the union the local-handling one.
- Suspending bodies: the existing one-fence rule (a `try { } catch { }`
  spanning a suspension propagates one error type) is unchanged; the routing
  clause happens BEFORE propagation, so a routed `try` counts as its TARGET
  type for the fence — which gives suspending code a new tool, not a new
  restriction.

### 4. `try_` means NON-BLOCKING, nothing else

Reserved for non-blocking variants of potentially blocking operations —
`try_receive`, `try_lock` keep their names and their meaning. The standard
shape: the blocking op's error type with the payload optionalized —

```saw
func receive(&var self) -> Result<T, ChannelError>       // blocks
func try_receive(&var self) -> Result<T?, ChannelError>  // never blocks
```

`Ok(None)` = nothing yet. Would-block is NOT an error — it is the normal
answer to a poll — while `Err(Closed)` still surfaces on a poll, because a
closed channel must not look like an empty one. Where a non-blocking variant
has no error path at all, plain `T?` suffices (`try_lock -> Guard?`).

### 5. The boundaries

- **The fault line survives.** Programmer errors — bounds, overflow, shift
  range, contract violations — stay PANICS, exactly as the M3 fault ruling
  put it for the kernel (`send(<bad data>)` faults; a full queue returns a
  status). What moves to Result is DYNAMIC conditions: OOM, closed,
  cancelled, OS refusal. `Vector.set` out of range still panics; `push` out
  of memory now reports.
- **Hidden allocations CANNOT return Results** — interpolation, an escaping
  closure's environment, coroutine frames have no expression to hang a `try`
  on. They stay panics, with `--no-hidden-alloc` as the opt-out for code that
  cannot accept that. The spec states this boundary explicitly rather than
  implying total coverage.
- The compiler-inserted `copy()` hook stays infallible (design 219's
  contract) — a retain is not an allocation.

### 6. Consequences already banked

- **DQ-230b is resolved by this brief**: `send -> Result<Void, ChannelError>`
  with `ChannelError { Closed, Cancelled, Alloc(e: AllocError) }`; `try_send`
  retires (its closed-channel panic asymmetry dies with it). The DF-230a fix
  (the `Cancelled` case + cancellation wake, landing in the Aug-17 batch) is
  forward-compatible with this end state.
- Migration is the largest behavioral-contract flip yet, but design 151
  (discarding a Result is a compile error) means THE COMPILER FINDS EVERY
  SITE — the corpus migration is driven by clean errors, not greps.

## Units

Obligation 2 (consumer sweep) is unit 0 and gates the rest; obligation 1's
position matrix for the routing clause lives in unit 1; obligation 3's
conformance rows lead unit 3.

- **Unit 0 — the consumer sweep.** Who relies on the panic tier: the
  `alloc_*_oom_panic` examples (their expectations INVERT), every
  `try_`-twin call site, any test asserting the panic message, the
  `--no-hidden-alloc` docs, the design-123 sections of spec/skill/README.
  Output: the migration matrix the later units execute, one row per consumer.
  No code changes.
- **Unit 1 — the routing clause.** Parser (`try(as EnumType.Case)` prefix
  production; `try!`/`try?`/catch exclusions), typechecker (case-payload
  check, target-type substitution at the fence), coro ANF (routed try in
  suspending positions), diagnostics (wrong case arity, non-enum target,
  case cannot hold the source type — each naming the fix). Position matrix
  tested row by row: statement, let-init, expression positions (args,
  interpolation, match subject, `??` RHS), suspending body, inside
  try/catch blocks. Lands with the grammar in LANGUAGE_SPEC.md + skill.
  Usable immediately; changes no existing behavior.
- **Unit 2 — `SystemError` + compound shapes.** The public type; `IoError`
  gains `System(e: SystemError)` (its own mini consumer sweep — net/file
  matchers); `ChannelError` gains `Alloc(e: AllocError)`.
- **Unit 3 — the std flip, per-type sub-units, conformance rows first.**
  Order: alloc → Vector → Map/Set → Data → String/StringBuilder → Box/Arc →
  Channel (+ `try_send` retirement) → net/file. Each sub-unit: ops flip to
  Result, twins retire, corpus call sites migrate (compiler-driven), docs
  rows update. Each is its own gated commit; the suite is green after every
  one — the corpus migrates WITH the type it uses, never ahead.
- **Unit 4 — the non-blocking family.** `try_receive`/`try_lock` (and any
  poll-shaped op the sweep finds) standardize on the §4 shape.
- **Unit 5 — docs closeout.** Spec's error-handling chapter rewritten around
  the three tiers + routing clause; skill digest; README; the
  hidden-allocation boundary stated; design 123's sections marked superseded.

## Gates

Compiler brief: per-commit full suite + sos_runner both arches
(`battery.sh suite sos`); terminal full battery. The corpus migration
sub-units are the ones most likely to disturb IR determinism ordering —
`irdet --all` is in the terminal battery as always.
