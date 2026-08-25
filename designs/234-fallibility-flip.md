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

## Unit 2 — the error-type reshapes (Aug 22, on the Aug-22 ruling)

RULED: option 1. The collision below is recorded as it was found; what follows
is what landed.

### What landed

**The seam.** `__saw_rt_last_raw_code() -> word`, added to
`RUNTIME_ABI_SYMBOLS` and described in `rt/ABI.md` beside
`__saw_rt_last_syserror`, which now STAMPS it — that stamp is part of the
classifier's contract, stated in the document, because a runtime whose
classifier forgets it answers a stale number. The ABI.md entry records the
amendment against the "Pin deviation" paragraph rather than editing that
paragraph out, and shows both of its grounds surviving: the status word still
carries only the tag (so the one-negated-word `(status, value)` correspondence
with the SOS syscall ABI is untouched, and the change is additive in the same
sense DF-215a's tag widening was), and std still never reads errno after the
fact (the value is frozen INSIDE the runtime in the same statement that
classifies; the deleted v1 `__saw_rt_errno` read the LIVE global whenever std
asked, which is what the v1 `tcp_listen` `close()` clobbered).

**PER-THREAD storage**, in both host bodies, over pthread thread-specific data —
the idiom `rt/common/op_budget.saw` already uses, for the same reason (Saw has
no thread-local storage). Not a taste call: errno is per-thread, MT TaskGroups
classify on several threads at once, and a process-global slot would hand one
thread's refusal to another. The ~30-line block is duplicated into
`host_macos/net_os.saw` and `host_linux/net_os.saw` because it has to sit in the
file that CLASSIFIES and that file is per-host; each object is its own
translation unit, so factoring it into `common/` would have meant a second
exported symbol in every hosted binary.

**The freshness rule is written down as the caller's obligation**, because it is
the one thing that can go quietly wrong. A tag the runtime SYNTHESIZES without
consulting errno leaves the slot alone (`-Invalid` for an unrecognized open
mode, `-NotFound` for a name with no IPv4 address), so std splits its factories:
`IoError.of(syscall:tag:)` reads the seam and is used only where a runtime op
just classified, and `IoError.of(syscall:kind:)` is the std-raised form whose
`code` is `0`. Three std paths take the second one — the six design-102
cancellation exits (through a new `io_cancelled` helper, which also reads better
than the `io_error(op, SYS_INTERRUPTED)` it replaces), `resolve_error` (whose
tag may be runtime-synthesized AND whose classification happened on an offload
WORKER thread), and `net_read_once`'s scratch-buffer refusal, which needed a
sentinel of its own (`NET_NO_SCRATCH`, far below the tag space) so the read
loops can tell it from an OS refusal. Without that split, a resolve failure
would have logged whatever errno the thread last saw — most often `EAGAIN` from
a park loop.

**SOS: nothing to stamp.** `sos/rt/common` exports four seams and implements no
OS-op family and no `__saw_rt_last_syserror`, so a body would be dead code. The
ruled answer is DOCUMENTED for when one lands, in ABI.md and in lib.saw's
runtime-seam header: SOS answers its NATIVE STATUS WORD, which numerically
coincides with the SysError tag because the status half of the ratified
`(status, value)` syscall ABI IS that tag space (sos/spec.md §5.7) — a
documented coincidence, not a second copy of the number.

**`IoErrorKind`**, 21 cases, raw-backed `UInt8` on the frozen tag numbers, so
`IoErrorKind.from(raw:)` IS the mapping and there is no second table to drift.
Names are un-abbreviated (`ConnectionReset`, `AddressInUse`,
`ResourcesExhausted`) per the API-naming doctrine, tag 16 `Other` becomes
`Unknown` — the escape hatch §2 asks for — and there is no `Ok` case: an
`IoError` is a failure, and a kind meaning "no failure" would be the errno-lie
in miniature. Tag 0 and any tag past the table both answer `Unknown`.

**`IoError` is `{syscall, kind, code: Int32}`.** `syscall` STAYS: §2's snippet
shows the two fields it is reshaping and does not discuss the third, and
dropping it would have turned every message into a bare `io error (not found)`.
Only `kind` reaches the rendered text, deliberately — the raw number is
platform-specific (`ECONNREFUSED` is 61 on macOS, 111 on Linux) and putting it
in the text would make every pinned string host-dependent. So **the three
rendering pins did not change**, against unit 0's prediction that they would;
the reshape is invisible to `"{e}"` by design. `code()` now returns the raw
`Int32` where it used to return the tag, which unit 0 proved breaks no reader
(both fields private, zero `.code()` call sites tree-wide), and `kind()` is the
new name for the branchable half.

**`ChannelError` gained `Alloc(e: AllocError)`** and renders through the leaf.
Nothing produces it yet — `send`'s `NoMemory` arm still panics until unit 3's
channel sub-unit, which is where DQ-230b closes.

Pin: `examples/io_error_kind_and_raw_code.saw` — the rendered text, the kind, a
`match` on it, nonzero code for an OS refusal, zero for a std-raised failure, an
unmapped tag landing on `Unknown`, and the `ChannelError.Alloc` rendering. It
asserts the KIND exactly and the raw NUMBER only as nonzero: the number is a
platform constant, and pinning it would pin the platform.

Docs fixed with the code rather than deferred to unit 5, because each was a
statement the reshape made false: LANGUAGE_SPEC's std.net paragraph (which said
"there is no accessor for the raw platform number, because the runtime ABI does
not carry one across the seam") and its `ChannelError` declaration, and the
saw-lang skill's `IoError` and `ChannelError` entries plus its import-gate list.

### FINDING: DF-245a — an `init`'s declared return type is unchecked

Probing whether §2's sibling question for unit 3 — can an allocating
CONSTRUCTOR return a `Result`? — has an answer turned up a compiler defect, filed
as DF-245a with its mechanism and sweep. Short version: an `init` may be declared
with any return type, the call site ignores it and types the result as the
receiver, and codegen then emits IR that does not verify. So the answer is NO,
and unit 3's allocating constructors (`Vector(capacity:)`, `Data(capacity:)`,
`Arc(value:)`, `Mutex(value:)`, `Channel()`) have to become static factories —
which makes "retire the `try_` prefix" a DELETION of the `init` plus a rename of
the twin, at 194 call sites.

### The collision (as found, before the ruling)

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

## Unit 3 — the CHANNEL sub-unit only; the rest is BLOCKED (Aug 22)

### What landed

`Channel.send`'s allocator arm is `Err(Alloc(e))` and `try_send` is gone. This
was the one sub-unit the flip could execute without the two defects below: `send`
already returned a `Result`, so only its `case NoMemory` changes and no caller's
SHAPE moves. `try_send` had exactly ONE real call site in the whole tree, which
is why the corpus half is three files rather than three hundred.

**DQ-230b is EXECUTED.** Its entry (in `done_aug18-aug25.md`, resolved on paper
Aug 17) says "Executes with 234's Channel sub-unit"; this is that. The asymmetry
it recorded — `send` reporting a closed channel and panicking on the allocator,
`try_send` doing exactly the reverse, neither able to carry the other's failure —
was a consequence of one error slot, and §1's compound-enum rule removes the
constraint rather than choosing between the two halves.

`examples/alloc_channel_send_oom_panic.saw` INVERTS and is renamed
`alloc_channel_send_reports_oom.saw` (the Aug-9 naming ruling). It asserts more
than the panic could: the rendered error, that NOTHING was queued, and that the
channel still works after the refusal — the all-or-nothing half, which a panic
could never check because it never returned.

**Conformance row A01 opens a new section.** The allocation tier had ZERO rows —
design 123 landed ahead of the conformance suite and design 191's audit predates
the flip — so obligation 3's rows for it are all new. They land WITH the
sub-unit that flips their type rather than as one opening batch: a row can only
assert one of the two behaviors, and the corpus has to agree with it. The INDEX
section says so, so the partial coverage is auditable rather than looking like a
gap.

### Why the rest is blocked, and by what

Two compiler defects and one uncounted census row, all found by probing rather
than by reading:

- **DF-245a** — an `init`'s declared return type is never checked against the
  receiver. The declaration is accepted, the call site types the result as the
  receiver anyway, and codegen emits IR that does not verify. So a fallible
  CONSTRUCTOR is not expressible, and `Vector(capacity:)`, `Data(capacity:)`,
  `Arc(value:)` and `Channel()` cannot simply start returning `Result` — they
  have to become static factories, which is a public-API deletion at 194 call
  sites rather than a signature change. (`Mutex(value:)` is exempt: design 186
  made it inline, so it allocates nothing.)
- **DF-245b** — `try!` panics without the error it was handed
  (`panic at F:L: try! failed`). `try!` is the behavior-PRESERVING migration for
  a call site that does not want to handle OOM, so the flip would replace
  `Vector.push: allocation failed` with `try! failed` at every site that takes
  it. Fixing that is a diagnostic-wording ruling plus a pin change
  (`examples/try_force_panic.saw` expects the current text verbatim).
- **The count unit 0's matrix never took.** It counts the 56 twin call sites and
  the 24 std alloc-panic sites, but not the CALLERS of the infallible ops those
  panics belong to — and design 151 turns every one of them into a compile error
  the moment `push`/`append`/`insert` return a `Result`. Counted Aug 22: **1434**
  such sites (examples 902, sawc/std 115, the other trees 417) plus the 194
  constructor sites above. Each needs a spelled disposition, and WHICH one is a
  decision the brief does not make: `try!` reproduces today's behavior visibly,
  `try` cascades `Result` through the callers' signatures, and `let _ =` hides
  the failure the flip exists to surface.

Two census corrections while counting, both against unit 0's own text: the twin
family is **20**, not 19 (its table lists 20 rows under a heading saying 19), and
**FIVE** twins have no infallible partner method, not four (its paragraph names
five under a heading saying four).

## Unit 3 — THE FLIP, complete (Aug 25, branch `design-234-c`)

Four commits, each gated. What follows is the landing plus the review surface
the ratified protocol asks for: every non-mechanical site with its chosen
spelling.

### The twin table, all 20 rows

| twin | fate |
|---|---|
| `Vector.try_push` | RETIRED into `push` |
| `Vector.try_reserve` | RENAMED `reserve` (no infallible partner) |
| `Vector.try_with_capacity` | RETIRED into `Vector(capacity:)`, now fallible |
| `Vector.try_copy` | KEPT — DF-257b; `copy()` is the `ExplicitCopy` hook |
| `Data.try_push` | RETIRED into `push` |
| `Data.try_set` | RETIRED into `set` |
| `Data.try_append` | RETIRED into `append` |
| `Data.try_append_bytes` | RETIRED into `append_bytes` |
| `Data.try_reserve` | RENAMED `reserve` |
| `Data.try_with_capacity` | RETIRED into `Data(capacity:)` |
| `Data.try_detached` | RETIRED into `detached` |
| `StringBuilder.try_append` | RETIRED into `append` |
| `StringBuilder.try_append_char` | RETIRED into `append_char` |
| `StringBuilder.try_with_capacity` | RETIRED into `StringBuilder(capacity:)` |
| `Map.try_insert` | RETIRED into `insert` |
| `Set.try_insert` | RETIRED into `insert` |
| `Box.try_make` | RETIRED into `make` |
| `Arc.try_make` | RETIRED into `Arc(value:)` |
| `Channel.try_make` | RETIRED into `Channel()` |
| `Channel.try_send` | retired with unit 3's channel sub-unit (Aug 22) |

The FIVE with no infallible partner method turn out to be two renames and three
retirements into a constructor: `Vector.try_reserve` and `Data.try_reserve` had
nothing to merge with; the three `try_with_capacity`s merged into the `init`
DF-245a made expressible. Unit 0's "a rename, not a merge" reading was right
about the shape and wrong about the count once the constructors could flip.

### The two hazards

**(a) The collection literal.** The filing was about the container's nullary
`init`; that half does not bite (`Vector()`, `Map()` and `Set()` allocate
nothing). The real hazard is the per-element synthesized `push`/`insert`, which
has no expression a `try` could sit on — §5's boundary reached from the other
side. `_build_collection_literal` forces the `Result` and panics naming the
error, through one funnel (`_force_synthesized_result` over
`_emit_forced_result_panic`, which `try!` shares). Conformance A16.

That teaching landed inert in commit 3.1 and did NOT fire when the flip arrived:
the instantiation lookup keyed on the LLVM layout plus the Ok payload's
spelling, and an ordinary program has three `Result` instantiations sharing
`{ i32, [16 x i8] }` with a `Void` Ok. The literal dropped every refusal
silently, and the whole battery stayed green. A16 is what caught it; the fix
adds the Err payload's spelling as a second key. Recorded because the lesson is
the row, not the bug: a teaching commit with no test is a teaching commit that
can be wrong for two commits running.

**(b) The two construction checkers.** RECORDED, not reconciled — DF-257a, with
both directions probe-refuted. `_check_struct_init` matches an init by
subset-plus-defaults, `_check_module_struct_init` by set equality, so a
defaulted parameter resolves bare and is `no matching initializer` qualified.
The fallible form makes it worse (a second, misleading error at the caller's
`try`), but the flip does not reach it: no constructor it touches has a default,
and the one std init that does never becomes fallible.

### The non-mechanical sites

Everything in `examples/` and the package `tests/` took `try!` mechanically off
design 151's own diagnostics. These are the rest, per tree.

**std, the reporting side.** `Vector.map`, `Map.keys`/`values`, `Set.to_vector`
and the whole set algebra (`union`/`intersection`/`difference`/`is_subset`/
`is_superset`), `String.split`/`to_data`, `Env.args`, `Command.arg`/`env` all
flip to `Result<_, AllocError>`: each BUILDS a container, so each carries the
refusal out. `Command.output` becomes `Result<CommandOutput?, AllocError>` —
`Ok(None)` keeps its old "the child could not be run or the wait was cancelled"
meaning and the allocator gets a channel of its own, which is §4's peel applied
to a non-channel. `StringBuilder.append_scalar` becomes
`Result<Int?, AllocError>` for exactly the same reason: `Ok(None)` still means
"not a scalar value".

**std, the mapping side.** `File.read`/`write` and `Directory.list` answer
`IoError.of(syscall:kind:)` with `ResourcesExhausted` — the domain already had
the word, so §1's carry-the-leaf rule maps rather than re-enumerates.
`net_read_once` folds a refused grow into `NET_NO_SCRATCH`, the third answer its
own scratch failure already had, and the read loops turn that into the same
`ResourcesExhausted`. `TcpStream.write(s: String)` does the same for its
staging buffer. `cbor.saw` maps onto `EncodeFault.BufferFull` and
`DecodeFault.TooLarge` through two FREE helpers (`__cbor_encoded`,
`__cbor_scanned`, plus a value-carrying `__cbor_encoded_data`) — free rather
than methods because the argument is a `&var self` call on a field and a
`&self` receiver beside it is an exclusivity violation.

**std, the forcing side.** Three families, each with a structural reason:

- `Vector.copy()` — the `ExplicitCopy` hook. Panics BY HAND, naming the method,
  rather than through `try!`, so the message does not read `try! failed` out of
  a std file the caller never opened. Conformance A17, DF-257b.
- every `format(&self, into: &var StringBuilder)` body (36 in std) — the
  trait's signature carries no error channel, and the path it serves has to work
  with the allocator refusing everything, which is why design 137 gave it FIXED
  storage where an overrun truncates and no `AllocError` exists.
  `FixedStringBuilder`'s four appends and `net.saw`'s `resolve_error` are the
  same shape.
- the executor — `TaskGroup`'s slot growth, worker handles and free list, all
  through one `__exec_alloc_or_fault`, because `group.spawn { }` is a FORM.
  `Task.spawn`'s background group already panicked for this reason.
- `@synthesize`d `Deserialize` forces its vector `push` (`_force_expr` in
  `typechecker/serde.py`): routing would mean naming `DecodeError`'s
  construction in code synthesized into the USER's module, where std.serde's
  fault vocabulary may not be imported at all.

**Three std sites spell `match` where `try` would read better**, each citing
DF-257c at the line: `Map.insert`'s recursive tail, and the reservation in
`Map.keys`/`values`. They revert when that closes.

**blade + libs** (~200 sites): `try!` at the leaves, `try` kept wherever a
Result was already flowing. `libs/toml`'s builder methods (`add`, `add_table`)
and `libs/semver`'s format bodies force; flipping toml's builder API is its own
change and is NOT done here. FLAGGED: the mechanical force pass initially
converted three PRE-EXISTING propagations in `resolver.saw` (`visit` twice,
`validate`) into `try!`, which turned a dependency cycle from a reported error
into an abort — caught by blade's own `resolver_cycle`/`conflict`/
`two_sources` tests, restored, and worth naming because a blunt
`let _ = try` -> `try!` sweep is exactly how a propagation quietly becomes a
crash.

**devtools** (~55) and **selfhost** (~190): `try!` throughout. A devtool that
runs out of memory should die loudly, and selfhost's `LexError` has no
allocation case — giving it one is that tree's own change.

**sos + freestanding** (6 sites): `try!`, including the `SosStatus` format body.

### The silent-unsoundness save

`_is_multithreaded_taskgroup_init` decides whether a group turns on the
Send-on-frames gate by matching the SHAPE of its initializer. Every
`TaskGroup(threads: N)` in the language is now written
`try! TaskGroup(threads: N)`, and the shape test could not see through the
`try` — so the gate turned itself off at every multi-threaded group and five
pinned Send refusals started compiling. `_unwrap_try` is the funnel the test
asks first; its docstring names its entry point, and a second shape test on an
initializer belongs there rather than beside it. This is what obligation 2's
consumer sweep is FOR: the sweep names who relies on the old behaviour, and a
syntactic shape test relies on it in a way no type checks.

### Findings

- **DF-257a** — the two construction checkers select an init differently
  (recorded; the flip does not reach it).
- **DF-257b** — §5's infallible `copy()` hook leaves one alloc `try_` twin the
  flip cannot retire. Three ways out, all needing a naming ruling; held at
  "keep the name", with A17 pinning the boundary that creates it.
- **DF-257c** — a propagating `try` in a GENERIC body is resolved once and
  reused across monomorphizations. PRE-EXISTING; the minimal repro needs no
  `init`. Pinned XFAIL.
- **DF-257d** — the `$0` shorthand is invisible to the implicit-parameter scan
  inside a `try` operand. PRE-EXISTING. Pinned XFAIL.

### Conformance

A03-A12 (one row per op family that reports) and A13-A17 (the edges: the
retired prefix's absence, and the four places §5 keeps a panic). Z01 RE-READ —
its closure body now has two things it could be refused for, so the covering
test spells `try!` and the exclusivity refusal is the only one left standing.

### Gates

suite 2220 passed / 6 xfailed (xfail delta +2, both new DF pins), freestanding
both arches, citations (6 open, 0 stale), bootstrap stage0-2, selfhostlex,
bench, `irdet --all` (1376 examples, 0 mismatches), sos both arches.

## Unit 4 — the non-blocking family (Aug 22)

`try_receive` is `-> Result<T?, ChannelError>` per §4: `Ok(Some(v))` a message,
`Ok(None)` nothing yet, `Err(Closed)` closed AND drained. The dequeue itself
became a private `_take_one` and the closed test sits in the two public callers,
so the coroutine transform's seam (`__try_receive_result`) is untouched BY
CONSTRUCTION rather than by care — it keeps calling `_take_one` and never names
`try_receive` at all.

16 call sites, three shapes. Most take `try!` (the channel is never closed in
those tests, so behavior is identical and the diff is one word). Conformance K66
takes a real `match`, and is BETTER for it: the poll after the drain now
distinguishes "closed, nothing will ever come" from "empty right now", which is
exactly the distinction §4 exists to restore, and that file could previously only
say the queue was empty.

**§4's discipline audit.** The other two `try_` keepers already conform:
`SpinLock.try_lock -> R?` and `Once.try_get -> T?` are the no-error-path short
form §4 blesses (each polls something that may not be ready and cannot fail any
other way). `selfhost`'s `try_read_int_suffix` is the third in-tree meaning
("may not match") and stays out of scope, as unit 0 recorded — not std.

### TWO FINDINGS, both pre-existing, both hit by §4's shape

- **DF-245c** — one spawned task ANYWHERE stops every `return None` at a
  `-> Result<T?, E>` from typing, in functions that task never calls. The second
  typecheck pass, over the post-transform AST, does not push the peeled `Ok`
  payload onto the `None`. Probed four ways to isolate the trigger as "the
  transform ran", not "the call graph reaches it". std.channel writes the
  annotated-local form (`let absent: T? = None`) instead, which is the same
  shape `_delivered`/`_closed` already used beside it for the neighbouring
  two-layer reason. Pin:
  `examples/result_optional_none_survives_the_transform.saw` (XFAIL).
- **DF-245d** — a propagating `try` in an optional-binding SCRUTINEE inside a
  suspending body is refused. DF-244a fixed the same shape under `return` and a
  block tail; `while let` / `if let` / `guard let` are the sibling positions its
  sweep did not reach. This is the one that costs something: §4's drain idiom is
  `while let v = try ch.try_receive()`, where the `try` peels the error channel
  and the `while let` peels the optional, and a spawned consumer cannot write it
  today. `examples/while_let_channel_drain.saw` spells `try!` and cites the
  entry. Pin: `examples/suspending_binding_scrutinee_propagates_a_try.saw`
  (XFAIL, `while let` and `if let` rows).


## Unit 5 — docs closeout, PARTIAL (Aug 22)

What is TRUE after units 1, 2 and 4 landed, and nothing beyond it.

LANGUAGE_SPEC §5 gained two subsections ahead of "Try Variants":
**Error-type doctrine** (the three tiers, with `ChannelError` as the worked
compound; the share-case-names-never-wrapper-enums rule; `Box<any Error>` as the
application tier std never produces; and why there is no stdlib-wide errno enum)
and **`try_` means non-blocking** (§4's `Result<T?, E>` shape, the `T?` short
form where there is no error path, and the `try` + `while let` drain that peels
the two channels apart). The saw-lang skill and README carry the user-facing
subset of the same.

THE TWO RULED BOUNDARY SENTENCES (user, Aug 22) landed here. Neither site
changes behavior; both are now stated where a reader meets them:

- the ERASED-ERROR box joins the hidden-allocation family, from the other
  direction — those sites cannot report because no expression can carry the
  report, and this one cannot report because the report is what ran out. A
  program that must not meet it names its error type, which is the tier std
  stays on.
- `Data.[]`'s copy-on-write separation stays under the ACCESSOR RULE, beside
  the bounds panic it shares a body with. Splitting one of the two failures out
  as a value would make `d[i]` mean two different things by which failure it
  met; `try_detached()` is the preflight that attempts the allocation where a
  failure has somewhere to go.

NOT landable at the time, because each described unit 3's end state: marking
design 123's sections superseded, and removing the `try_` twin table.

CLOSED Aug 25 with unit 3. LANGUAGE_SPEC's "Allocation failure" is rewritten
around the one tier: the twin table is gone, the operation list replaces it, and
a "Where a refusal still panics" subsection names the five (compiler-inserted
allocations, the collection literal, `copy()`, `Data`'s subscript, the `String`
layer with `Printable.format` beside it). The `Data`, `StringBuilder`, `Box` and
slab sections lost their twin references; the `Arc`/`Box` example is the flipped
spelling and compiles as shown. The saw-lang skill's allocation section is
rewritten the same way, and README gains the one-tier sentence in the
allocation bullet and in the error-doctrine section.
