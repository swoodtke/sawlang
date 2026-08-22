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
  genuinely mix.** `ChannelError { Closed, Cancelled, Alloc(e: AllocError) }`.
  Never re-enumerate the inner vocabulary — carry the leaf. The OS boundary
  is the special case §2 covers (`IoError` as kind + raw code).
- **NO stdlib-wide errno-style enum as a return type.** Its defining property
  is that every signature lies: `push -> Result<_, StdError>` claims failure
  modes it cannot produce, and every exhaustive match grows dead arms. errno's
  flatness was C's lack of sum types.
- **`Box<any Error>` is the APPLICATION aggregation tier. std never erases.**
  The erased `Result<T, Box<any Error>>` machinery stays exactly as is, for
  app code that does not care.

### 2. No public `SystemError` — `IoError` is the OS-boundary type
### (amended Aug 17, user: an errno wrapper reimports the errno-lie)

There is NO public generic system-error type. The two needs it seemed to
serve are met differently:

- **The OS boundary** is genuinely open-vocabulary — the errno set is huge,
  platform-dependent, and not closed, so precision is unattainable there in
  principle and the honest type is "the OS refused, with details." That type
  is `IoError`, restructured as **curated portable kind + raw code**:

  ```saw
  struct IoError {
      kind: IoErrorKind   // NotFound, PermissionDenied, ConnectionReset,
                          // TimedOut, Interrupted, ..., Unknown
      code: Int32         // the platform's raw truth, ALWAYS present
                          // (0 where the platform has none)
  }
  ```

  The `code` rides on EVERY IoError, not just `Unknown` — classification
  loses information by design (EACCES and EPERM both map to
  PermissionDenied) and the log wants the real one. `Unknown` is the escape
  hatch for codes the portable vocabulary has no word for. Two rules make it
  sound: **classification is diagnostic, not contractual** — correct
  handling of `Unknown` treats it as opaque failure, never "I know which
  errno this secretly is" (that is what `code` is for, explicitly); and
  **growth is loud** — promoting a code out of `Unknown` into a new kind
  breaks exhaustive kind-matchers at compile time rather than silently
  rerouting. On SOS/freestanding, `code` carries the platform's native
  status; the portable half works on targets that never heard of errno.
  The rt-internal `SysError` stays internal (seam maps errno → it → kind).

- **The generic conditions** that recur across domains (Alloc, Cancelled,
  TimedOut) are NOT hoisted into a shared wrapper enum — that would
  re-create the errno-lie one level down (`ChannelError.Sys(SystemError)`
  claims a pure in-process channel can fail with OS refusal, and every
  match goes two levels deep). Instead: **share leaf payload types and case
  names; never share wrapper enums.** Each domain enum declares exactly the
  generic conditions that apply to it, flat, spelled identically everywhere,
  carrying the shared leaf (`AllocError` keeps size/align):

  ```saw
  enum ChannelError { case Closed, case Cancelled, case Alloc(e: AllocError) }
  enum TimerError   { case Cancelled, case Alloc(e: AllocError) }  // no Closed
  ```

  A domain that cannot time out has no TimedOut case — signatures stay
  exact. Cross-domain generic matching ("is this transient?"), if ever
  needed, is a small trait with predicate methods — deferred until a use
  case exists.

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
  RIDER (added Aug 17, user): **DF-232h** — a closure's TAIL expression does
  not auto-wrap into a declared `Result` return type (its `return` does, and
  the Optional analogue works). Same funnel area, and the flip multiplies
  closures returning Results, so it lands here: fix the closure tail path to
  reach the Result wrap, flip the cited pin
  `examples/closure_tail_autowraps_result.saw`.
- **Unit 2 — the error-type reshapes.** `IoError` restructures to kind +
  raw code per §2 (its own mini consumer sweep — net/file matchers and every
  `.code` reader); `IoErrorKind`'s starting vocabulary chosen from what the
  rt seam actually maps today; `ChannelError` gains `Alloc(e: AllocError)`.
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

GATE AMENDMENT (user, Aug 21, after this brief was ratified): a compiler
change now gates per-commit on the full suite + `tools/freestanding_runner.py`
(both arches), NOT sos_runner; a commit that TOUCHES `sos/` additionally gates
sos_runner on both arches. The terminal battery is unchanged and still carries
its `sos` stage. This brief's later units touch `sos/`, so those commits owe
both.

---

# Landing

## Unit 0 — the consumer sweep (Aug 22)

Two censuses, both probe-backed (every claim below is a compile or a run, not
a grep). THREE CORRECTIONS to the brief's own numbers, recorded because the
later units are planned off them.

### Correction 1 — the twin family is 19, not "~16 across nine std files"

19 alloc twins across **10** files. The brief's §"The decision" list omits
`try_set` and `try_append_bytes`, and counts `cbor.saw` (a consumer, not a
declarer) while missing that `once.saw` and `spinlock.saw` hold two of the
three NON-blocking ops.

| file | twins |
|---|---|
| `sawc/std/vector.saw` | `try_with_capacity`, `try_push`, `try_reserve`, `try_copy` |
| `sawc/std/data.saw` | `try_with_capacity`, `try_set`, `try_push`, `try_reserve`, `try_append`, `try_append_bytes`, `try_detached` |
| `sawc/std/stringbuilder.saw` | `try_with_capacity`, `try_append`, `try_append_char` |
| `sawc/std/map.saw` | `try_insert` |
| `sawc/std/set.saw` | `try_insert` |
| `sawc/std/box.saw` | `try_make` |
| `sawc/std/arc.saw` | `try_make` |
| `sawc/std/channel.saw` | `try_make`, `try_send` |

The three §4 keepers: `Channel.try_receive`, `SpinLock.try_lock`,
`Once.try_get`.

### Correction 2 — FOUR twins have no infallible twin, so unit 3 RENAMES them

`Vector.try_with_capacity`, `Vector.try_reserve`, `Data.try_with_capacity`,
`Data.try_reserve` and `StringBuilder.try_with_capacity` have no
`reserve`/`with_capacity` to merge into (compile-refuted: ``type `Vector` has
no method `reserve` ``). Retiring the prefix there renames a SOLE method
rather than collapsing a pair, which is a different migration shape — a caller
of `try_reserve` gets a rename, not a signature change.

### Correction 3 — `try_receive`'s §4 shape is a CHANGE, not a preservation

`try_receive` is `-> T?` today, and `receive` is
`-> Result<T, ChannelError>`, so a closed channel is currently
indistinguishable from an empty one on the poll path. §4's
`Result<T?, ChannelError>` fixes that and breaks all 15 call sites
syntactically (10 use `if let`/`while let`, 3 use `!`). That is unit 4's
work, not unit 3's, and it is the largest single call-site cluster in the
whole census.

### The migration matrix

| consumer | count | where | chosen semantic |
|---|---|---|---|
| alloc `try_` twins | 19 decls | 10 std files | retire the prefix; the twin's behavior becomes the ordinary op's (4 of them a rename — correction 2) |
| twin CALL sites | 56 | examples/ 45 (5 conformance), sawc/std/ 11 | migrate with the type; ZERO in blade/, libs/, sos/, devtools/, tools/, selfhost/, sawc/rt/ |
| panicking alloc sites in std | 24 | 12 std files | flip to `Result`; `Channel.send`, `File.read`, `File.write` already RETURN Result and only their alloc ARM changes |
| compiler-emitted alloc panics | 3 | closures.py (env), calls.py (spawn CB), core.py (String) | STAY panics — §5's hidden-allocation boundary, `--no-hidden-alloc` is the opt-out |
| `existentials.py:402` boxing panic | 1 | codegen | its stated rationale is "`Box<T>.make` parity"; that parity moves under unit 3, so this site needs a ruling the brief does not give — HELD for the user |
| `Data.[]`'s COW-separation panic | 1 | `data.saw:222` | a place accessor's `lend` prologue: an expression exists to hang a `try` on, but it is a subscript — the brief names no home for it, HELD for the user |
| oom-panic examples that INVERT | 6 | examples/ | expectation flips from `EXPECT: panic` to a Result match |
| oom-panic examples that STAY | 2 | `alloc_string_oom_panic`, `alloc_string_no_degradation` | they pin the HIDDEN String allocation, which §5 keeps as a panic; they become the positive statement of that boundary |
| tier-demonstration examples | 8 | examples/ | bodies migrate; `try_with_capacity.saw` and `box_try_make.saw` are NAMED for retiring methods and get renamed (Aug-9 naming ruling) |
| `--no-hidden-alloc` tests | 5 | examples/ | untouched — they already pin §5's boundary |
| `IoError` field readers | 0 | — | both fields are PRIVATE (compile-refuted), and there are ZERO `.code()` call sites tree-wide, so unit 2's reshape breaks no reader |
| `IoError` rendering pins | 3 | examples/ | update the pinned strings with the reshape |
| `ChannelError` consumers outside `channel.saw` | 2 real | examples/ | both go through `describe()`/`{e}`; NO `case Closed`/`case Cancelled` match exists anywhere outside `channel.saw` |
| `ChannelError.describe()` pins | 2 | examples/ | `"the receiving task was cancelled"` is pinned twice; `"channel is closed"` by nothing |
| `AllocError` field readers | 4 | 2 examples/ | `size`/`align` are PUBLIC and stay |
| conformance rows | 0 existing | INDEX.md | obligation 3's rows for the alloc tier are all NEW; Z01 (`push` inside a `with_var_ref` window) must be re-read once `push` returns a Result |
| implicit `IoError` carriers | ~20 files | blade/, devtools/ | they never spell `IoError` — it reaches them through `try` into `Box<any Error>`; the reshape leaves them alone, the FLIP does not. Typechecked by the `bootstrap` stage only |
| doc mentions of `try_` | 30 + 19 lines | LANGUAGE_SPEC.md, SKILL.md | unit 5; README has ZERO |

Trees with NOTHING to migrate for the twin family: `blade/`, `libs/`, `sos/`,
`devtools/`, `tools/`, `tests/`, `selfhost/`, `sawc/rt/`.

Two trees the brief's unit list never names and that the flip WILL reach
through the infallible ops (`push`/`append`/`insert`): `devtools/` and
`selfhost/`. `devtools/irdet` and `devtools/bench` are themselves battery
lanes, so breaking either takes the gate down with it.

### The `try_` prefix has a THIRD in-tree meaning

`selfhost/lexer/src/lib.saw:786` `try_read_int_suffix` means "may not match".
It is not std and is out of §4's scope, but it is the one in-tree name that
reads wrong once the prefix narrows.

## Unit 1 — the routing clause + DF-232h (Aug 22)

`try(as ErrorType.Case) f()` lands as specified. ONE chokepoint each side
(obligation 1): `_check_try_routing` in the typechecker and the routing block
in `_generate_try_propagate` in codegen, each docstring naming its entry
points. The clause rides the `TryExpr` NODE, so every position a `try` can sit
in is served by construction rather than enumerated.

Position matrix, `examples/try_routing_clause.saw`, 13 rows: statement, `let`
initializer, argument, interpolation, `match` scrutinee, `??` RHS, `return`
operand, tail, TWO SOURCES routed into one enum, inside a
`try { } catch { }` block, a MODULE-QUALIFIED target, a suspending body, and
two error types in one suspending body (which the fence now sees as one).
Two controls in the same file pin that the prefix slot took nothing away: a
trailing `as` is still a value projection, and `try (f())` is still a
parenthesized expression.

Refusals, `examples/try_routing_clause_refusals.saw` (9) +
`examples/try_routing_clause_needs_a_case.saw` (the parse-level one, its own
file because a parse error ends the compile): `try!`/`try?` with a clause,
clause + `catch`, a non-enum target, an unknown type, an unknown case, a
payload-free case, a two-field case, a payload-type mismatch, and a clause
naming no case. Each reports EXACTLY ONCE — a malformed clause says what the
author meant to send, so the caller does not then check the SOURCE type
against the signature and complain a second time about a type they never
intended.

TWO MORE POSITIONS are probe-verified and NOT yet pinned — free rows for
whichever unit next touches this file:

- **a routed `try` inside a CLOSURE body**, which propagates out of the
  closure (design 213), so the routing target is checked against the
  CLOSURE's declared error type. `run({ x in try(as LocalError.Alloc)
  grab(x) })` prints `err A30` on the failing path and `ok 6` on the other.
- **route THEN erase**: a routed `try` in a function returning
  `Result<T, Box<any Error>>` boxes the ROUTED enum at the propagation edge,
  so `"{e}"` renders through the domain enum's own vtable (`L/A30`, not the
  leaf's `A30`). This is the one ordering the two mechanisms could have got
  wrong, and codegen has it right because routing runs first by construction.

DF-232h landed as the extraction it asked for: `_autowrap_into_result` in
`sawc/typechecker/statements.py` is now the ONE Result auto-wrap ladder, over
four entry points (function tail, method tail, `return`, closure tail). It
closes DF-213b too — the same defect filed from another angle.

TWO FINDINGS, both pre-existing, both named by mechanism:
- **DF-244a (FIXED, its own commit ahead of unit 1)** — a propagating `try` in
  a `return` (or a block tail) inside a suspending body never reached design
  196's error landing, because `_lower_stmt`'s `return` branch sits above the
  dispatch. Five expression shapes under `return` failed, two as ICEs, and all
  five passed when bound to a `let` first. Design 234 multiplies exactly this
  shape, which is why it was fixed rather than filed and left.
- **DF-244b (open)** — a bare `None` TAIL at a `Result<T?, E>` cannot type
  itself, in a NAMED body as much as a closure, so it is not the
  closure-vs-named disagreement DF-232h was. `return None` works.

## Unit 2 — HELD FOR A RULING (Aug 22)

**Not started.** §2's `IoError` reshape cannot be implemented as ratified
without changing a DIFFERENT ratified decision, so it stops here rather than
being coded around.

### The collision

§2 requires `code: Int32` to ride on EVERY `IoError`, carrying "the platform's
raw truth", and says why: classification loses information by design (EACCES
and EPERM both become `PermissionDenied`) and the log wants the real one.

The raw errno never crosses the runtime seam. `__saw_rt_last_syserror()`
(`sawc/rt/host_macos/net_os.saw:87`, `host_linux/net_os.saw:82`) reads errno,
classifies it, and returns ONLY the tag — the local `e` holding the raw value
is discarded inside the runtime, so nothing downstream can recover it.

That is deliberate and RECORDED. `sawc/rt/ABI.md:174-182`, the "Pin deviation"
paragraph, refuses exactly this on two grounds: a single negated-word return
cannot carry a tag AND a raw errno, and SOS has no errno to preserve. Design
117 chose to buy diagnostic richness by growing the TAG table instead, and
DF-215a's five off-loopback tags are that promise being kept. §2 asks for the
thing 117 declined.

### The three ways out, costed

1. **A new additive seam** — `__saw_rt_last_raw_code() -> word`, set by the
   same runtime code that classifies, read at the same instant. Genuinely
   additive in ABI.md's own sense (a new symbol; no existing signature moves,
   so `runtime_abi.py`'s arity/width check and `make abidoc`'s symbol-set check
   see what they saw before), and it does NOT reintroduce the POSIX-errno
   fragility 117 rejected, because the value is captured inside the runtime
   beside the tag rather than read after the fact by std. Costs: both hosts,
   `sos/rt/common` (which must answer something), `runtime_abi.py`, `ABI.md`.
   The SOS answer needs a ruling of its own — §2 says both "0 where the
   platform has none" and "on SOS/freestanding, `code` carries the platform's
   native status", and for SOS those are the same number as the tag.
2. **Widen the status word** to carry `(tag, code)` — changes the return
   contract of every status-carrying op. NOT additive; contradicts the
   one-word/`(status, value)` correspondence with the SOS syscall ABI that
   ABI.md gives as the reason for the encoding.
3. **Ship `code` as always 0 on hosted** — contradicts §2's own words, and
   makes the field useless exactly where it was meant to earn its keep.

Storing the TAG in `code` is not a fourth option: `kind` already is the tag,
so the struct would carry one fact twice and §2's motivating sentence would be
false.

### What is NOT blocked

The rest of unit 2 is independent of this: `IoErrorKind`'s vocabulary is
already sitting in the tag table (22 tags, 21 with words —
`sys_error_name` has no arm for `Other`, which falls through `case _` and is
the existing `Unknown` analogue), and `ChannelError` gaining
`Alloc(e: AllocError)` needs nothing from the seam. Both were left unstarted
so unit 2 lands as one piece once the ruling arrives — a `kind`-only reshape
would implement the half that changes nothing observable and skip the half
that motivated it.
