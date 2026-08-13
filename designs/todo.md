# Saw — Open Work Tracker

Open items ONLY. Landed work lives in `designs/NN-*.md` + git history
(this file was pruned Jul 30; see git history of this file for the old
landed recaps). Conventions: cite source designs in [brackets]; VERIFY
items need a probe before being treated as real work.
Historical/landed recaps: designs/todo_aug1-aug9.md (split Aug 9);
older history is in this file's git log (pruned Jul 30).

## The next queue — designs 195-202 + 153 (ALL RULED Aug 10, awaiting dispatch)

Every open ruling from the overnight run plus the parked backlog was
settled in the Aug-10 morning review; each has an authored brief.
Order (soundness → capability → consistency; typechecker briefs serial,
disjoint surfaces parallel):

1. ~~**195 integer width agreement**~~ — **LANDED Aug 10**, all five units,
   tracked battery green. DF-192f and DF-192g closed; DF-195a (an implicit
   widening extending by the TARGET's signedness — a second wrong answer,
   found by unit 1's probes) closed with them. Four findings filed:
   DF-195b/c (transfer-position narrowing and sign flip through the
   platform pair — a CONVERSION question, owed a ruling), DF-195d (may an
   integer literal adopt `Float`?), DF-195e (two widening positions with no
   source type threaded to them). See `designs/195-*.md` for the four
   decisions the units needed beyond the brief's text.
2. ~~**198 duplicate match arms are errors**~~ — **LANDED Aug 10**, all three
   units, tracked battery green. DF-192d closed: one chokepoint judges an
   exact duplicate arm, both lowerings behind it, ranges and guards exempt.
   The corpus sweep found ZERO duplicate arms outside the pin itself (1882
   .saw files). One finding filed: DF-198a (a guarded or tuple-nested match
   over an all-payload-free enum is a codegen ICE — the general pattern path
   reads a tag out of a shape that enum does not have). Two spellings the
   brief expected to behave otherwise are recorded in `designs/198-*.md`.
3. ~~**199 nested-call refs join the Law**~~ — **LANDED Aug 10**, all four
   units, tracked battery green. DF-188j closed: a nested call's `&`/`&var`
   arguments join the outer call's access set and meet the unchanged path
   test, so overlapping paths error on every tier and disjoint ones are
   untouched. Two answers the units produced: the receiver-position variant
   was NOT already caught (`p.total(reset(&var p))` compiled and read the
   receiver at its pre-reset value), and the consumer sweep over all 1890
   tracked `.saw` files found ZERO offenders — the rule landed without
   changing any existing program. No findings filed. Sweep record in
   `designs/199-*.md`.
4. ~~**200 receiver-copy place write**~~ — **LANDED Aug 10**, all three
   units, tracked battery green. DF-176c closes: the fourth vanishing-write
   spelling (an EXCLUSIVE place window on storage inside a `&self` receiver)
   is the design-176 error, judged in the place lowering; the borrows-body
   half is ratified as intended. Telling the refusal from the carve-out needed
   a new fact — WHERE an accessor lends from — so `place_transform` records
   each lending path's shape and `place_uses` walks it against the receiver's
   real type, which extends design 176's inline-vs-indirect walk by the one
   hop it could not take. The consumer sweep found ZERO exclusive windows on
   inline fields in `&self` methods across std, blade, libs, sos and devtools
   (fifteen grep hits over the write and call forms, none of them a place).
   One finding filed: DF-200a. Sweep record and the two answers the units
   produced in `designs/200-*.md`.
   ∥ **153 statics→enums sweep** (place lowering vs std .saw — disjoint).
5. **196 coro × erased errors + captures** (DF-193a, DF-192b/c,
   DF-191a) — solo (coro_transform + result cells).
6. ~~**201 spawn reference parameters** (design-88 relaxation, 189 u4,
   ratified)~~ — **LANDED Aug 10** (in a worktree), all four units, tracked
   battery green. DF-201a closes. Two answers: the declared-after-group case
   does NOT fall out of design 188's rule (188 walks capture lists only, and
   the argument shape was a silent use-after-free), and the DF-138a dual-role
   trampoline had to forward a reference parameter rather than pass its name.
   See `designs/201-*.md`.
7. ~~**202 Atomic move-only** (DF-186a, ruled GO by census) — after 153
   (both touch std .saw).~~ LANDED Aug 10. The census held: five holders
   flushed, nothing else. Units 2 and 3 landed SWAPPED — a tier flip
   without its cascade fails builtins for every program, so the
   declarations had to go first.
8. **197 declaration-position names** (DF-194a + rule-7 parse_type
   bypasses) — last; UX debt, feeds the parser port.

~~**204 std type identity**~~ — **LANDED Aug 10** (dispatched beside 196, in a
worktree), all four units, tracked battery green. DF-153b and DF-153a close
together: design 144's `(defining module, name)` reaches std, where each FILE
is a module, so a std type declared without `public` is that file's alone. What
it cost: std's public type surface is now DECLARED — 40 `public` markers,
sorted by hand against the prelude gate and the documented API, which is the
design-80/82 gate finishing the job for types. Counted afterwards from the
compiler's own view: 101 type declarations (29 in `builtin.saw`, 72 in `std/`),
48 declared public, 24 file-private. Two design-144-era bugs surfaced on the way and
are fixed: `name.split('$')[0]` at seven sites read a MODULE QUALIFIER as a
monomorphization suffix (one helper, `type_identity.declaration_base`, replaces
all seven), and a coroutine FRAME struct must never be qualified since the
compiler names it by string (`Struct.is_synthesized`). Two findings filed:
DF-204a (four std internals the compiler spells by string still reserve their
names) and DF-204b (a closure's symbol carries its source LINE). See
`designs/204-*.md`.

Also ratified Aug 10 with no work owed: design 183's two
implementation decisions (blocking-conflict = error not upgrade; Float
in the offload set) stand as landed.

Design 195 detail: all typed operands of an operation must be the SAME
type (implicit promotion from bare literals only — no promotion
ladder); value-branch arms are TRANSFERS through the existing
checkpoint (lossless widening legal, like `return`). 12-row position
matrix; conformance rows first; consumer sweep owed.

## FUTURE WORK — design 214, Raft under deterministic simulation (Aug 12)

**Not scheduled, not ruled, no units authored.** Brief:
`designs/214-raft-simulation-dogfood.md`, written from a live
investigation of the tree so the ruling session starts from facts.

Raft as a pure I/O-free state machine behind three seams (Clock /
Transport / Storage) over a simulated backend — virtual clock, scripted
network faults, seeded RNG — asserting the paper's four safety
invariants across replayable seeds. The first dogfood target to load
ownership-without-lifetimes, cancellation, existential dispatch and the
error surface at once, and the first with a correctness oracle stronger
than "it ran".

Enabling work the investigation found missing, each its own future
brief: a seeded RNG (there is none in the tree), `File.sync` (crosses
the frozen `rt/ABI.md`), a virtual-clock executor mode, a `TcpStream`
read deadline, and two VERIFY probes (single-threaded scheduler
determinism, `Map` iteration order). The RNG, `fsync` and **the `select`
/ receive-with-timeout ruling** are each dispatchable ahead of and
independent of any Raft code — `select` is a language question worth
answering either way.

## Design 216 — lifting `T: Copy` off Vector's closure and sort APIs (PROPOSAL)

**Not scheduled, not ruled.** Brief: `designs/216-vector-copy-bounds.md`.

`map`, `each`, `each_indexed`, `fold` and `sort` carry a `T: Copy` bound their
algorithms do not need — inherited from `iter`/`enumerated`, which do. The
effect is that a `Vector` of move-only elements cannot be mapped, folded or
sorted at all. Four probes in the brief show the bound comes off: `&T` element
closures for the first four (and the transform need not be `sync`, so
suspending transforms survive), and `swap` plus borrowed comparison for `sort`.
A NoCopy `Vector` sorts end to end today, written from outside std.

- **DF-216a — ICE: any closure naming `self` inside a method** fails with
  ``'self' not found in current scope``. 20-line repro; not specific to the
  receiver (a free function fails identically), so the trigger is the
  identifier. Workarounds: hoist the field to a local, or pass `&self` to the
  closure as an explicit parameter. ZERO occurrences in std, which is why it
  went unseen. An ICE, so a finding on its own terms.
- **DF-216b — SOUNDNESS: the comparison operators bypass the transfer
  checkpoint.** `a.compare(b)` on a NoCopy type is correctly refused; `a > b`,
  the same call, COMPILES. The operator passes the by-value `other` as a
  borrow, so a conformance that exercises its declared right to `move other`
  deinits a value the caller still owns — three comparisons of a two-element
  vector print FIVE deinits, from fully safe code with no `unsafe` at the call
  site. The DF-132a shape at the operator lowering. Two fixes wanted together:
  the missing check (one rule, two entry points — obligation 1), and
  `Comparable`/`Equatable` taking `other: &Self`, which closes it by
  construction and is what makes NoCopy comparison legitimate. **Blocks 216's
  `sort` half; the `map`/`each`/`fold` half is independent.** Core trait
  signature change, so its own brief.

**Class sweeps run Aug 13 (obligation 4's first exercise; matrices + mechanism
anchors in the brief).** DF-216b IS a class: SEVEN unsound positions
(`>`-family, `==`/`!=`, match guards, `@synthesize` memberwise, enum payload,
tuple, generic bodies under bounds) — one mechanism, the operator path never
builds a call node, so the stopgap funnel is `_check_binary_op`'s trait gating
and the `&Self` signature change closes the whole matrix by construction.
DF-216a is NOT a class: one missing `SelfExpr` arm in the closure-capture
funnel (`collect_names`), every other binding kind probed green; a second small
entry point at the capture-list grammar. The sweep also found:

- **DF-216c — generic METHOD type-arg inference fails on labeled arguments.**
  `h.probe(other: 99i64)` on `func probe<U>(other: U)` cannot infer `U`; the
  two-param shape misreports a matching label as unknown. The identical free
  function infers fine, so it is method-specific. Verified by hand; repros
  named in the brief.

## Obligation-4 retro triage of recent DF fixes (Aug 13 — sweeps QUEUED, not run)

Reviewed the recent fix waves for class-shaped mechanisms the fixes may have
patched position-by-position. Two sweeps owed; ready to dispatch (the 216
sweep prompts are the template). NOT dispatched — session token budget.

1. **Coro-frame owning-binding positions** (the DF-206a/b/f + DF-210a/b/f
   family — SIX fixes, two designs, one mechanism space). The fixes built the
   right oracle (`Namespace.read_policy`, asked by `_store_binding_in_slot` +
   `_slot_store_consumes`) but the class quantifier is the OTHER axis: which
   binding/discard constructs' lowerings ASK it. Covered: match arm payload,
   `if let`/`guard let` (incl. hoisted scrutinee temps), `let _`, tuple
   destructure. Unprobed siblings for the matrix: `??` RHS binding an owning
   payload, `?.`-chain consumption via the `_`-blessed forms, nested
   destructuring, for-loop bindings, closure captures of owning values in
   driven bodies, place writes into frame slots. (`while let` does not exist —
   N/A.) DF-210d's dead `frame_move_read` marker is already flagged "folded
   into whatever next touches the frame-slot family" — this sweep is that
   touch. Evidence shape: deinit counts in suspending bodies, per position.

2. **Labeled-call recognition divergence.** DF-190b (a LABELED call was not a
   call to the coroutine transform's effect census) and now DF-216c (generic
   METHOD type-arg inference fails on labeled args) are two subsystems caught
   mishandling the same input shape. Sweep: census every recognizer that
   dispatches on call shape (coro effect graph, inference, overload
   resolution, place analysis, capture analysis), probe each with
   labeled x positional x method/free x generic.

Reviewed and NOT owed a sweep (mechanism already funneled or swept by its
fix): design 196's erased-error family (one canonical spelling, unit 2; the
capture funnel + positions, unit 4), DF-176c (design 200 unit 3 committed its
sweep record), DF-203a/b (fix installed `really_suspending` as the ONE shared
definition, four routes named), design 195's platform-width family (units
quantified over ALL typed operands / ALL value-branch arms; remainder is
design 205's authored brief).

## Design 215 — the LLM client (Python reference LANDED; Saw port FUTURE WORK)

Brief: `designs/215-llm-client-saw-port.md`. Both programs sit in
`devtools/dogfood/programs/`. User order (Aug 12): Python first, port
second, debugging language issues as they surface.

**LANDED — `llm_client.py`**, the reference and the port's spec: stdlib
only, OpenAI-compatible `/v1`, with streaming, tool calling, gated file
editing, a system-prompt file, and an interactive REPL (vi bindings,
persistent history, slash commands). Verified against LM Studio on
`Mac-Studio.local:1234`.

**ALSO LANDED — `llm_client.saw`**, the first Saw attempt (one-shot,
non-streaming), verified end-to-end against a local mock. lexdiff and
astdiff green over 1937 files with it in the corpus.

**Environment fact worth carrying beyond this brief:** macOS 15+ gates
Local Network access PER APP, so an unapproved binary gets
`EHOSTUNREACH` for ANY LAN address while loopback works. Not a Saw bug —
a freshly `cc`-built C binary behaves identically. Every future net
dogfood program on this machine will hit it.

Four findings, all probe-reduced; evidence and repros in the brief:
- **DF-215a — std.net can name NO remote-connect failure.** Five errnos
  unmapped, all collapsing to "other error" with the cause discarded;
  the suite never leaves loopback, which is why it went unseen.
  **Land first** — small fix, and it is what made the session long.
- **DF-215b — `move` of a frame local in a nested block's TAIL
  expression is refused in a suspending body.** 25-line repro, ready to
  become a cited pin; the diagnostic's advice does not apply.
- **DF-215c — hand-written JSON pays `\{` at every brace**, since a bare
  `{` in a literal opens an interpolation.
- **DF-215d — the wrapped `&&` (DF-172d) re-confirmed.**

Port blockers, staged A-F in the brief: DF-215a first; **std.json — tool
use is where hand-rolled JSON stops working, making this its third
consumer and the first that cannot route around it**; incremental line
reads for streaming; a `TcpStream` read deadline; and **a line-editing
story, probably its own brief**, since Saw has no terminal surface at
all.

## Design 212 findings — the long-function decomposition sweep (Aug 12)

- **DF-212a — `return` inside a closure literal is checked against the
  ENCLOSING NAMED FUNCTION's return type, not the closure's own.** Hit while
  extracting unit 4's arg-scanner closures (`blade/src/cli.saw`), which
  wanted an early `return 1`/`return 2` to report how many tokens a branch
  consumed. `_check_return_statement` (`sawc/typechecker/statements.py:2825`)
  reads `self.current_function`/`self.current_method` unconditionally — it
  never tracks entry into a `ClosureExpr`, so a `return` textually inside a
  closure is type-checked as if it were a `return` from whichever `func` or
  method lexically contains the closure. When the two return types disagree
  this is a loud, confusing error (a closure returning `Int` reports
  `expected return type` as the OUTER function's unrelated type); when they
  happen to agree it would silently compile with the WRONG target — untested,
  but the mechanism gives no reason to expect otherwise. `designs/todo.md`'s
  own DF-187c entry (design 187, "Design 185" section) already describes the
  coro_transform's OWN model as "a closure's own `return` is untouched" when
  rewriting suspending bodies — i.e., the compiler's mental model already
  assumes closures have local returns; the typechecker's `_check_return_statement`
  just never implements it. Minimal repro:
  ```saw
  func call_it(body: (Int) -> Int) -> Int { body(5) }
  func outer() -> String {
      let r = call_it({ x in
          if x > 0 { return 99 }
          0
      })
      "r={r}"
  }
  ```
  `error: expected return type `String` but got `Int`` — pointing at `return
  99`, which correctly would want to return `99` from the closure (typed
  `(Int) -> Int`) but is instead checked against `outer`'s `-> String`. NOT a
  blocker for unit 4 on its own: this codebase's established closure idiom is
  already value-expression tails (`if`/`match` as the closure's last
  expression, no `return`), which every existing closure in
  `sawc/std/taskgroup.saw` already uses. Superseded as unit 4's actual blocker
  by DF-212b below, which rules out passing a closure to the helper at all.

- **DF-212b (BLOCKED unit 4 as designed) — a closure literal argument to a
  free function corrupts an unrelated enum's type identity, ACROSS the whole
  caller, when the caller sits in a module that gets cross-module-embedded
  for an unrelated reason.** Isolated by bisection in
  `blade/src/cli.saw`/`blade/src/main.saw` (both restored — no trace left in
  the tree): adding
  ```saw
  func scan_args(args: &Vector<String>, start: Int, handle: (Int, Int) -> Int) { ... }
  ```
  to `cli.saw`, and calling it with a closure LITERAL argument
  (`scan_args(&args, 2, { av, i in 1 })`, body irrelevant — even a trivial
  return-1 stub) from inside ONE branch of `Cli.parse()`'s value-returning
  `if`/`else if` chain (each branch builds `Cli(command: BladeCommand.X)`,
  both types declared in `cli.saw`), makes EVERY branch of that chain fail
  with ``field `command` expects type `BladeCommand` but got `BladeCommand` ``
  — the same printed name, two distinct identities, which is design 144's
  signature for a type resolved twice under two different (module, name)
  answers. The FIRST failing line is `return Cli(command: BladeCommand.Help)`,
  textually BEFORE the branch that calls `scan_args` at all. Bisection (each
  step re-verified against the real blade project, `--module-path`
  toml/semver/imgformat, via `sawc/sawc.py blade/src/main.saw`):
  - Declaring `scan_args` unused: compiles.
  - Calling it with a NON-closure argument (`scan_args(&args, 2) -> Int`, no
    `handle` parameter at all): compiles.
  - Calling it with a closure argument, `main.saw`'s own `main()` NOT
    suspending (a `main()` that only calls `cli.Cli.parse()` and prints the
    result, or that also imports `src.manifest`/`src.builder`/`src.tester`
    but never calls anything suspending): compiles.
  - Calling it with a closure argument AND `main()` transitively suspending
    (its real body's `Build` arm reaches `Builder.build` -> `Command.run`,
    which suspends): FAILS, reproducibly, regardless of whether the closure's
    own parameter types name a reference (`(&Vector<String>, Int) -> Int` and
    the reference-free `(Int, Int) -> Int` both trigger it).
  - Unrelated to design 212 units 2/3: reproduces identically with
    `sosimg.saw`/`builder.saw` reverted to their pre-212 content.
  Reading: `main`'s body becomes ONE coroutine frame because it eventually
  suspends, so the frame machinery has to carry every earlier local
  (`parsed_cli: Cli`) across the whole function — including the ones bound
  before the branch that will never suspend. Something about registering a
  closure-typed parameter's argument at that call site, during whatever pass
  builds or re-resolves that frame, mints a SECOND identity for
  `BladeCommand` that prints the same but does not `==` the first. NOT
  reproduced in an isolated two-file `import src.cli` + `Cli.parse()` project
  with no suspending call anywhere — the suspending-frame condition is load-
  bearing and a fully minimal standalone repro is still owed. Worked around
  by AVOIDING the closure entirely (not a "workaround" of THIS unit's design
  goal — a genuinely different, still-mechanical extraction): unit 4's
  `scan_args` takes `value_flags: &Set<String>` and returns a
  `ScanResult { flags: Map<String, String>, positional: Vector<String> }`
  instead of a `handle` closure, which collapses the SAME three loops with no
  closure anywhere in the call graph. `run`'s loop (no flag recognition at
  all — it collects every token, "--"-prefixed ones included) is left as its
  own small loop rather than forced through the flag-shaped scanner, which
  would have changed its behavior (a `blade run --foo` argument must still
  reach the child program's argv).

## Design 153 findings — the magic-values→backed-enums sweep (Aug 10)

- ~~**DF-153a — two std FILES cannot declare the same type name.**~~ **CLOSED
  by design 204** (Aug 10). Each std file's PRIVATE types are that file's:
  identity `State$m$std_once`, name bound only in its own module view. The
  vehicle is `tools/test_std_private_type_names.py` (conformance row B10, the
  battery's `stdtypes` stage) — it drops a second private `State` into the std
  tree, rebuilds the builtins, and asserts two identities, two layouts and two
  method symbol families. Original text:

  **DF-153a — two std FILES cannot declare the same type name.** Design 82
  makes each std file its own module and design 144 makes type identity
  `(defining module, name)`, but the std sources are type-checked as ONE
  `builtins` unit, so a second declaration of a name collides:
  ```
  sawc/std/once.saw:64      enum State: Int { case Unset = 0, ... }
  sawc/std/spinlock.saw     enum State: Int { case Unlocked = 0, case Held = 1 }
  → error: enum `State` is defined multiple times  --> builtins:38:1
  ```
  A user program with the same two modules compiles (that is what design
  144 landed). Not user-facing — only a std-authoring constraint — but it
  is the rule not holding where it is written to hold. The sweep worked
  around it by naming SpinLock's enum `LockState`, which is the spelling
  the skill's STYLE bullet uses for exactly these two constants anyway.

- ~~**DF-153b — a private std TYPE reserves its simple name for every
  program.**~~ **CLOSED by design 204** (Aug 10). A std type declared `public`
  keeps its exposure exactly; one declared without `public` is FILE-private —
  qualified identity, bound only in its own file's view, reachable through no
  import form. 24 std-internal type names are free for user programs now, and
  a std module's surface is a thing it SAYS rather than a thing that happens.
  Both pins flipped (`examples/user_enum_name_vs_private_std_enum.saw`,
  conformance row B09); row B12 is the fence that a PRELUDE name is still
  reserved. **The sweep's blocked item is UNBLOCKED**: `std.net`'s five `SYS_*`
  and `std.process`'s `SYS_WOULD_BLOCK` can take the `SysError` name rt/ABI.md
  gives them, since a private std enum no longer collides with the
  `enum145_*` tests' own `SysError`. Mech follow-up, alongside blade's
  `ElfSegFlag` naming decision below; design 204 deliberately did not do the
  conversion. Original text:

  **DF-153b — a private std TYPE reserves its simple name for every
  program.** USER-FACING, and the reason the sweep's `std.net` known-debt
  item did NOT land. Pin:
  `examples/user_enum_name_vs_private_std_enum.saw`.
  ```saw
  enum OpenMode: UInt8 { case Read = 0, case Write = 1 }   // a user program
  func main() { print("{OpenMode.Write as UInt8}") }
  → error: enum `OpenMode` has no variant `Write`
  ```
  std.file's private `enum OpenMode` wins, and the diagnostic names a
  declaration the author cannot see, import or find. This is exactly
  DF-140h — a private std `static` used to reserve its name the same way —
  fixed for statics and never for TYPES. A struct/enum name is what a user
  is most likely to pick, and std's private types are invisible, so the
  reserved set is unknowable.
  **What it cost this brief.** Giving `std.net`'s SysError tags the name
  rt/ABI.md gives them (`SysError`) broke three EXISTING tests
  (`enum145_methods`, `enum145_raw_backed`, `enum145_traits` — each
  declares its own `enum SysError`), so converting a std statics family
  into a std enum is not behavior-preserving until this is fixed: it
  widens the set of names std silently reserves. `std.net` and
  `std.process`'s SYS_WOULD_BLOCK are therefore left as statics, and the
  two std enums that DID land (`LockState`, `SeekWhence`) reserve two more
  names in the meantime. The fix is DF-140f/h's module-local identity
  applied to type declarations.

- **DF-153c — a fixed-width backed enum costs two casts at a word-wide
  seam.** Not a bug; the datum the brief asked the sweep to produce.
  `SysError` is `UInt8` because its numbers are ABI (design 47), but every
  seam that carries one types it `word`, so the use site reads
  ```saw
  if r == 0 - ((SysError.WouldBlock as UInt8) as Int) { ... }
  ```
  against the old `if r == -SYS_WOULD_BLOCK`. std.file's `OpenMode` already
  paid this (`(mode as UInt8) as Int`) at one site; the rt net ops pay it at
  a dozen. The same shape appears at every `Atomic<Int>` state machine —
  `LockState`/`Once.State` project with `as Int` per touch — which is what a
  hypothetical enum-typed `Atomic<E>` would remove. Two candidate answers if
  it is ever worth a design: a widening projection that reads the enum
  straight to the wider integer (one `as`), or `Atomic<E>` over a raw-backed
  enum. Recorded, not proposed.

### The sweep's census (what converted, and why the rest did not)

CONVERTED: SpinLock `UNLOCKED`/`HELD`; std.file `SEEK_*`; the rt-side
`SYS_*` tag space in all four rt modules; the spawn redirection bits on
both sides of the seam; sosrt's two abort codes.

NOT CONVERTED, by reason:
- ~~**Blocked by DF-153b**~~ **UNBLOCKED Aug 10 by design 204** — ready for a
  mech follow-up, not done there:
  `std.net`'s five `SYS_*` and `std.process`'s `SYS_WOULD_BLOCK` — both
  are the `SysError` vocabulary, and the name used to be taken by user
  programs. A private std enum reserves nothing now, so `enum SysError: UInt8`
  in `std/net.saw` no longer breaks `enum145_methods` / `enum145_raw_backed` /
  `enum145_traits`, each of which declares its own `SysError`. DF-153c's
  two-cast cost at the word-wide seams is the thing to re-read before doing it.
- **Host C constant families, not sets this code owns**: the ~20 `E*`
  errno numbers in each `net_os.saw` (an OPEN set — we name the ones we
  map, of hundreds); `EPOLL_CTL_*`, the kqueue `EV_*`/`NOTE_*`, the
  `CLOCK_*` ids, `AF_INET`/`SOCK_STREAM`/`PROTO_DEFAULT`, `WNOHANG`,
  `STDOUT_FILENO`/`STDERR_FILENO`. Each is one argument at one C call
  with no branch, no match and no `from(raw:)`, so the `as` ceremony
  swamps the gain (the brief's judgment clause).
- **Quantities, which is what a static is for**: every `*_OFF`/`*_LEN`/
  `*_SIZE`/`*_MAX`/`*_SHIFT`/`*_MASK` family — std.cbor's UTF-8 bounds,
  taskgroup's `BT_*` backtrace-table offsets, blade's ELF field offsets,
  the sos HAL's page/PMP/MAIR arithmetic, `Duration`'s scale factors.
- **Open sets**: `selfhost/lexer`'s 60 `B_*` byte codes (character
  values, not tags — the lexer compares against a sample of ASCII).
- **Refused by the language, correctly**: the arm64 HAL's `DESC_*`
  descriptor bits — `DESC_TABLE` and `DESC_PAGE` are both `0x2` (the same
  bit means different things at different levels), and a raw-backed enum
  rejects duplicate values. Two names for one number is what a static is
  still for.
- **Naming default set Aug 10 (check-in delegated reasonable decisions):
  `ElfSegFlag: UInt32` — the ELF spec's own noun (segment permission
  flags, p_flags), disambiguated from sosimg's `SegFlags` by the format
  prefix. Mech follow-up alongside the unblocked net.saw SYS_* once
  design 204 lands.** Original note:
  blade's ELF `PF_X`/`PF_W`/`PF_R` program flags
  (a genuine closed flag set — `PF_` is an abbreviation, and the nearby
  `SegFlag` names the OTHER format's flags, which these map into). Left
  rather than invented; a one-line ruling on the noun lands it.
- **examples/**: no incidental family. Every statics family there is the
  SUBJECT of its own test (const-init, `df140f`/`df140h` collisions,
  atomics counters) — the one exception, `serde169_hand_written`'s two
  wire tags, is scratch inside a hand-written-serde demo.
- **Docs**: no spec/README example models the pattern. Every statics
  example in either document is a size or a derived quantity, which is
  the form the ruling KEEPS; the ruling itself was already in the skill.
- **devtools/** was outside the brief's scope; `irdet`'s `EXIT_*` trio is
  the one family there.

## Design 204 findings — std type identity (Aug 10)

- **DF-204a — four std internals still reserve their names, because the
  compiler spells them.** `__TaskCell`, `__ResultCell` and `__VoidCell`
  (`std/taskgroup.saw`) are selected by NAME in `coro_transform.py` when it
  lowers a spawn, and `RangeInclusive` (`builtin.saw`) by
  `codegen/loops.py:226`. Design 204 marks all four `public` with a comment
  saying why: a qualified identity would rename the declaration out from under
  the Python string that builds the reference. So the ruling ("a private std
  type reserves nothing") holds for 24 of 28 genuinely internal types and not
  for these four. Not user-facing in practice (three are `__`-prefixed and
  `RangeInclusive` is a real language type), and a non-regression — they were
  reserved before too. The fix is for the four sites to resolve through the
  namespace's identity map instead of a literal, at which point the `public`
  markers come off; it wants its own small brief because "codegen names a std
  type by string" is a pattern worth counting before changing.

- **DF-204b — a closure's codegen symbol carries the LINE it was written on,
  so an unrelated edit above it renames the symbol.** Adding a three-line
  comment to `std/taskgroup.saw` moved eleven `__closure$__saw_bt_dump$1775_39`
  -style symbols by three. Harmless today (the names are internal and irdet
  measures run-to-run stability, not edit-to-edit), but it means an IR diff
  across two versions of the tree carries churn that has nothing to do with
  the change under review — which is exactly the measurement design 204 unit 3
  had to do by hand. Design 168 unit 3 already solved the analogous problem
  for literals with `mangle.content_tag` (name the thing after WHAT IS IN IT);
  the same treatment would fit a closure. Recorded, not proposed.

## Measured performance (Aug 10 — the warehouse benchmark)

The first profiling-backed performance entry (per the ruling: optimization
enters the tracker only with measurement behind it). The workload:
`devtools/bench/warehouse/` — a deterministic dispatcher/robots/orders
simulation, 200k ticks × 100 robots, implemented four ways with
checksum-identical output. Wall times on this host (contended by an agent
run; deltas consistent across alternating runs):

| impl | time | vs Rust |
|---|---|---|
| Rust `-C opt-level=3` | 0.22s | 1.0× |
| Swift structs `-O` | 0.45s | ~2.1× |
| Saw (default pipeline) | ~1.05s | ~4.9× |
| Saw IR → external `clang -O3` | ~1.08s | ~4.9× |
| Swift classes `-O` | ~1.37s | ~6.3× |

**The finding: the gap is LOWERING SHAPE, not the pass pipeline.** External
O3 on sawc's IR changes nothing, because every `v[i]` place access is
lowered as the full design-141 window protocol — the call site builds a
`{fn_ptr, env, dtor}` closure for the window body, calls the outlined
`Vector.[]` accessor, which reaches the body by an INDIRECT call at the
`lend` — and LLVM does not collapse the chain. ~3 calls + a closure build
per element access, tens of millions of times in the hot loop.

**Fix direction (brief AFTER the 195-202 queue drains):** a place-lowering
fast path — for a direct-storage accessor (Vector/Data `[]`), emit
bounds-check + GEP inline; the general protocol stays for accessors that
need it (epilogues, `#lend_var`, conditional lends). Acceptance: the
warehouse benchmark reaches Swift-structs territory (~0.45s) with every
check still on, checksums unchanged.

**Phase 2 (Aug 10 discussion, after the fast path lands + re-measure):
exclusivity-derived LLVM attributes, NOT a hoisting pass.** Repeated
access-chain hoisting with &var invalidation — the natural ask — is
exactly what LLVM's GVN/LICM already perform WHEN GIVEN ALIASING FACTS;
today every opaque call clobbers the world, so values reload. The Law of
Exclusivity statically proves what `noalias` asserts (one `&var` XOR
many `&`), and Saw's checked signatures license memory-effect attributes
(`&self` vs `&var self`, `sync`, no-escape) — with the exclusion set
ALREADY type-tracked: cell-carrying types, the `unsafe` effect,
`UnsafeMemory<_, Device>` (volatile, exempt). Rust's `&mut`→`noalias`
precedent. Emission is lowering-adjacent (ports with the design); LLVM
does the dataflow; per-attribute audit = "states what the checker
proved". A bespoke hoisting pass is REJECTED under the shapes-not-
optimizer rule above, and would be redundant with this.

**The standing rule this entry sets** (answers "will optimizing the Python
compiler hurt the port?"): improve the SHAPES codegen emits — lowering is
design, and a ported compiler inherits it — but build NO Python-side
optimizer machinery (custom passes, analysis frameworks, an inliner); LLVM
is the optimizer on both sides of any port. Pass-pipeline TUNING (an
O2-style llvmlite config) ports trivially and may ride any perf brief,
though the O3 null result says it buys little here.

Non-gating tracking: the `bench` battery stage times the Saw benchmark on
every battery run (checksums GATE — they are a behavioral pin; timing only
reports). Swift/Rust sources sit beside it as manual baselines so the
battery takes no swiftc/rustc dependency.

## Design 210 — annotated embedding (LANDED Aug 11; lands 206 with it)

`designs/210-annotated-embedding.md`. The user's ruling of Aug 11: an imported
NON-GENERIC function carries sufficient information for a caller to embed it in
its frame with NO re-typecheck; an imported GENERIC function exports what a
per-instantiation re-typecheck needs, and that recheck runs in the callee's HOME
module scope. Both paths built; design 84's std-only special case dissolved;
DF-206e closed by architecture, and design 206's two liveness fixes land with it.

**The embed contract is written down** (`coro_transform.py`'s module docstring,
indexed in the brief): six families an embed consumes — resolved expression
types, resolved callee SYMBOLS, effect/suspension facts, place/copy judgments,
what the transform stamps itself, and no-escape facts carried by construction.
Five ride the AST as declared `annotation(...)` fields; the sixth is the design-22
effect graph, keyed by `node_id` and therefore serializable on the same terms.
The astgraft lane is the closure proof. Kept serializable, NOT serialized —
separate compilation stays future work.

**The non-generic path** marks the expression kinds whose check CONSULTS THE
NAMESPACE (`FunctionCall`, `MethodCall`, `Identifier`, `MemberAccess`,
`StructInit`, `EnumInit`) with `Expression.embed_preserved`, and
`_check_expression` hands back the stored answer instead of re-resolving.
Marking only those is deliberate and was measured: everything else is judged
from its children's types and needs no scope, and skipping it LOSES facts,
because the post-transform pass accumulates context as it walks (a `try`'s error
type is collected from the `try` expressions the walk passes). The mark means
the subtree is CLOSED, which `_close_embed_marks` makes true bottom-up at the
splice boundary rather than assuming; the skip is wholesale, because descending
re-asks about nodes that were never independently askable (a module qualifier is
an `Identifier` its parent resolves). What the transform grafts, it answers for:
`_answered(node, type)` is the funnel, and a frame read takes the type of the
local it replaces.

**The generic path** keeps the per-instantiation recheck (designs 70/74) and
moves it into the template's home module through `_home_module_scope`, whose
docstring names all four rechecks. Plus the instantiation map: the caller's
concrete type ARGUMENTS are lent into the template's scope, because
`amplify<Lo>`'s body names `boost` (the template's module) and `Lo` (the
caller's) in one expression and neither namespace alone has both.

Conformance rows K21-K25 (`examples/conformance/INDEX.md`). blade compiles
again — 24 errors before, 0 after — which is DF-206e's stated acceptance.

Findings, all fixed:

- **DF-210a (FIXED) — a `match` arm's payload binding was stored into its frame
  slot by ALIAS.** For an ExplicitCopy or NoCopy payload the transfer checkpoint
  refused it outright: `cannot copy value of type `Cli` which implements
  ExplicitCopy`, anchored at `FILE:0:0`, on a program that writes no copy at all.
  Three of blade's 24 errors. PIN:
  `examples/conformance/K24_frame_slot_payload_binding_not_a_copy.saw`.
- **DF-210b (FIXED — silent memory corruption) — the `if let` twin moved
  UNCONDITIONALLY.** DF-182c made `_optbind_dispatch` store its binding with
  `move`, correct for a payload the binding OWNS and wrong for one whose read
  only RETAINS (the ImplicitCopy tier). For an `Arc` payload the frame released a
  reference the binding never held: probed on the pre-fix tree, `deinit` fires
  while the original still points at the value, `strong_count()` then reads freed
  memory, and a second `deinit` prints a garbage id. Only the `match` half was
  ever visibly broken, which is why the fix is ONE authority for both:
  `_store_binding_in_slot` asks `Namespace.read_policy` (design 193's funnel) and
  moves exactly when the read consumed. Both spellings balance now.
- **DF-210c (RECORDED, no action) — the declaration-time AST is not FULLY
  annotated.** Several node kinds carry no `resolved_type` — `StringInterpolation`
  and its `FormatPlaceholder`s among them — so "declaration-time annotated" and
  "fully annotated" are not yet the same statement. Design 210 does not need them
  to be (`_close_embed_marks` un-marks any subtree holding one, and it takes the
  ordinary path), but a future separate-compilation interface would, and the
  astgraft gate does not catch it: it polices whether a stamped attribute is
  DECLARED, not whether every node is stamped.
- **DF-210d (RECORDED, no action) — `ForceUnwrap.frame_move_read` is stamped and
  declared but has no reader.** Its documented job ("the read is a transfer even
  for a NoCopy payload") is done by the `frame_place_read` early return in
  `_check_value_transfer`, which covers move and non-move reads alike. Dead
  marker, or a second guard that never landed; folded into whatever next touches
  the frame-slot family.

**DF-206f is FIXED (unit 8)** — it was a real generated-code memory bug that
this branch's own widening exposed: a frame released one `Vector<String>` buffer
twice, through a consumed binding's slot and through the hoisted scrutinee temp
it came out of. The mechanism is DF-210f below; the pin is
`examples/coro_hoisted_scrutinee_released_once.saw`.

## Design 206 — executor park liveness (LANDED VIA 210, Aug 11)

**Landed as design 210 unit 0** — the five commits cherry-picked onto main and
integrated with design 201's spawn-reference lowering, which had never been
combined with them. No textual conflicts; `coro_transform.py` and `gmgate.py`
auto-merged, and both sides' rows are green in one tree (206's two liveness pins
flipped, 201's seven K-rows passing). The blocker below is closed by design 210.

The historical record of why it was blocked follows, unchanged.

**The branch was NOT landable on its own.** Both hangs were closed on the
`examples/` corpus (suite 1730 / 8 xfailed, gmgate both lanes green at -n 5,
ten-repeat stable) and the full battery was RED: `bootstrap` and `sos` failed
because blade no longer compiled. See DF-206e below.

`designs/206-executor-park-liveness.md`, with the unit-1 diagnosis written into
the brief. DF-203a and DF-203b were ONE bug, and it was neither of the two the
brief guessed: **the entry compile's effect graph has no node for any std
METHOD**, so the fixpoint answers NO to "does this body suspend?" for a body
whose only suspension is a std method call, and every consumer of that answer
lowers the body as if it never suspended. `main` was then never wrapped in the
entry executor (DF-203a: `accept`'s `io_wait` took the outside-frame lowering
that blocks the executor thread in `poll(-1)`), and a helper was never pulled
into the driven closure (DF-203b: `receive()` compiled to the library body,
whose `yield_now` is a NO-OP outside a frame — a bare spin). `sleep` differs
only in being an INTRINSIC, recorded as a direct source on its caller's own
node; timer-vs-reactor was a coincidence of the two spellings. Neither park
primitive nor the design-62 G3 receive lowering needed changing.
`really_suspending(nodes)` (effects.py) is now ONE definition of "really
suspends" shared by both typecheckers, with its callers and its four routes
named in its docstring.

Five findings; two fixed here, and the blocker was closed by design 210:

- **DF-206e (CLOSED by design 210, Aug 11) — the coroutine transform cannot embed
  a method of an imported USER module, and design 206 is what first asks it to.**
  The ruling was way (a): the honest fix, in its own brief. A non-generic embed
  keeps its home module's meaning by CARRYING its declaration-time answers rather
  than by re-resolving them anywhere; a generic one re-checks per instantiation in
  the template's home scope. blade compiles again (24 errors → 0), which is the
  acceptance this entry names. The frame-field half is DF-210a.
  Unit 2 makes `main` suspending whenever it REALLY suspends, by any route. That
  is what LANGUAGE_SPEC:5053 already promised, and its consequence is that the
  transform now runs on programs it has never run on. blade is one: its `main`
  reaches `Command.run` through `builder.Builder.build`, a method of the
  imported `builder` module, so the transform embeds that method as a sub-frame
  — and the spliced body is re-typechecked in the ENTRY module's namespace,
  where `builder`'s own private functions are not visible. blade dies on
  `resolve`, `read_file`, `sos_clang`, `arch_for_target`, `write_sosimg`
  ("function `resolve` is not directly accessible", 24 errors), which takes
  `bootstrap` and `sos` down with it. Design 84 built cross-module embedding for
  STD methods and its comment records the "static-inlining fix" that made
  `INVALID_FD` visible; std works because it is one scoping domain the entry
  compile has fully registered, and a user module is not.

  Minimal repro (two files, no blade): a `public` struct in `util.saw` whose
  method calls `Command.run` and a private sibling `inner()`, and a `main` in
  the entry module that calls the method — `error: undefined function `inner``.
  Beside it, blade's `main` shows the other half: the frame's own field copies
  are wrong too (`cannot copy value of type `Cli` which implements ExplicitCopy`
  at main.saw:0:0).

  THREE WAYS OUT, and the choice was a ruling: (a) fix the transform's
  cross-module splice so an embedded body keeps its home module's namespace —
  the honest fix, its own brief, and it makes "a suspending method drives at any
  depth" true across modules for the first time; (b) scope the entry-executor
  gate so it does not reach a user-module method (arbitrary, and it would leave
  the DF-203a family broken for exactly the multi-module programs that hit it);
  (c) accept the transform and change blade's shape. The user ruled (a) on
  Aug 11 and design 210 built it.

- **DF-206f (CLOSED by design 210 unit 8 — the mechanism is DF-210f below) —
  `irdet --all` printed OK and then exited 139 (SIGSEGV).** A real
  generated-code memory bug in frame teardown, not a harness artifact. It was
  DETERMINISTIC, it reproduced at **`-n 2`** in three seconds (the original
  "does not reproduce at 2 or at 119" was the same exit-code misreading
  corrected below), and Guard Malloc turned it into a first-bad-access fault on
  a guarded page. Crash frame, identical on every tree and every run:

      EXC_BAD_ACCESS (SIGSEGV)
      thread 0:
        Vector$2$String$GlobalAllocator_deinit
        __Frame_main___release

  `main`'s frame released the same `Vector<String>` buffer twice: once through
  the `guard let` binding's slot and once through the `__hoist0` slot holding
  the suspending scrutinee it was bound out of. See DF-210f.

  **A CORRECTION, recorded because the method matters.** This entry first said
  DF-206f was CLOSED by the design-201 integration, on a three-leg bisect that
  read exit 0 from two legs. That was wrong, and the error was entirely in the
  measurement: two legs ran as `./irdetbin --all > out.txt; echo "EXIT=$?"`, the
  shell moved the compound command to the background, and I read `out.txt` —
  which holds irdet's STDOUT and ends in `OK` — instead of the exit status,
  which had gone to the task's own output. The third leg appended `EXIT=$?` INTO
  the file, which is the only reason its 139 was ever visible. All four runs had
  crashed. Reading the artifact that is easy to reach instead of the one that
  answers the question is how a red gate reads green — and it also cost a real
  bug three hours of being called somebody else's.

- **DF-210f (FIXED) — a CONSUMED hoisted scrutinee never gave up its claim on
  the payload, so the frame freed it twice.** The mechanism behind DF-206f.

  The transform hoists a SUSPENDING scrutinee into a frame temp —
  `guard let out = cmd.output()` becomes `let __hoist0 = cmd.output()` plus a
  binding out of `__hoist0`, and `match fetch() { … }` becomes `__match0` the
  same way. When the payload's read policy is CONSUME (design 131's
  nocopy/explicit tiers), design 210 unit 3 stores the binding into its slot by
  `move` — correctly. But the temp still held the value, and nothing told it
  otherwise: `_optbind_dispatch`'s `forgets` list was fed only by an EXPLICIT
  `move` scrutinee (`if let r = move held`, DF-182c). The author cannot write
  that `move` here, because the temp is not a name they have. So `__release`
  dropped the binding's slot and the temp's slot, both pointing at one buffer.

  Fixed at both hoisters: `_hoist_temps` records the temps the transform makes
  (`__hoistN`, `__matchN`), `_slot_store_consumes` is the shared answer to "did
  this store take ownership" (the same `Namespace.read_policy` oracle
  `_store_binding_in_slot` uses), and the dispatch emits the clear the author
  could not write. The `match` side is per ARM, since only the arm that binds
  consumes. An ImplicitCopy payload is untouched: its read RETAINS, both slots
  legitimately own a reference, and both legitimately drop — which is DF-210b's
  rule seen from the other side, and why one oracle answers both.

  PIN: `examples/coro_hoisted_scrutinee_released_once.saw` — both spellings, an
  ExplicitCopy payload each. The exit code is the assertion; under Guard Malloc
  it faults on the first bad access.

Of the rest, two fixed here:

- **DF-206a (FIXED) — `let _ = expr` owed a frame field, and every discard in a
  driven body shared the one named `_`.** `_uniquify_bindings` (DF-151a) exempts
  `_` on the reasoning that it binds nothing: true of a match arm and an
  `if let`, false of a `let`. Two discards of different types were a bogus
  `cannot assign Int to field of type Data?` on a legal program — the
  `let _ = try! s.read()` / `let _ = h.join()` pair, which is what the DF-203a
  pin's own `main` says. The fix is not a rename: a discard drops its value AT
  the statement, so it owes no field at all, which also restores the timing a
  second same-typed discard had lost (it lived until frame death). THREE
  classifiers decide a `let`'s frame target and only two guarded `_`;
  `_classify_recv` now does too. PIN:
  `examples/coro_wildcard_discards_own_slots.saw`.
- **DF-206b (FIXED) — destructuring a tuple of OWNING elements in a driven body
  was a copy.** Design 77 item 10 lowered `let (a, b) = v` as a source temp plus
  `self.a = __destr0.0`, a tuple-index READ. Right for the `(Int, Int)` tuples
  it was built for; `let (a, b) = TcpStream.pair()` in a spawned task refused
  outright with "cannot copy value of type `TcpStream` which implements NoCopy",
  on a program the non-frame path compiles. Components now come out through the
  ordinary `DestructuringLet` over an explicit `move` of the source temp. PIN:
  `examples/coro_destructure_nocopy_into_frame.saw`; the copyable half stays
  pinned by `df151f_tuple_drop_glue`'s `destructured_across_suspend`.
- **DF-206c (FILED, not fixed) — a TAIL-position `ch.receive()` is a compile
  error.** `func take_one(ch: Channel<Int>) -> Int { ch.receive() }` is refused
  with "suspending call to `receive` ... appears in a nested/expression
  position; only a top-level `let x = receive(...)` or `receive(...)` statement
  is supported". That is design 62 G3's stated scope and a CLEAN anchored error,
  not a liveness bug — but it is the natural spelling of exactly the
  reusable-wrapper shape DF-203b was about, and the skill's own claim is that a
  suspending call embeds "in any EXPRESSION position" (design 120). Bind and
  return is the workaround (`examples/channel_receive_in_main.saw` does).
  Small: G3 needs the same ANF hoist the other suspending calls got.
- **DF-206d (OBSERVATION, no action) — the effect graph's std seam is keyed by
  NAME in the transform and by `node_id` in the typechecker.** Design 84's
  `_std_suspending_methods` is a set of `(struct, method)` name pairs, so a user
  struct named `TcpStream` with a method `read` would be treated as suspending
  by the coroutine transform's structural scan. Design 206's new table is keyed
  by `Method.node_id` instead — exact, and preserved verbatim across the std
  cache's pickle — so the two halves of the same seam now disagree about
  precision. Not a live bug (design 204 made std file-private types unnameable
  and the transform's imprecision is conservative), and not worth a brief on its
  own; worth folding into whatever next touches design 84's set.

## Design 203 dogfood wave 1 — findings (filed Aug 10, lead-triaged, both probe-confirmed)

Six Sonnet naive-implementer programs (203 u1). All six produced correct,
deterministic, spec-passing programs; the findings cluster in the
scheduler's park paths, stdlib seams, and diagnostics. The two (d)s:

- **DF-203a (LIVENESS — CLOSED by design 206, landed via 210 Aug 11): a task spawned before
  main's FIRST suspension never starts when that suspension is a REACTOR park.**
  `group.spawn(worker())` then `listener.accept()` blocks the executor on
  the OS reactor without draining the run queue, so a worker that would
  CONNECT to that listener never runs — permanent hang. The timer path
  (`sleep`) drains correctly (probe-isolated by the dogfood agent with
  three controls; hang re-confirmed by the lead on main). Breaks design
  89-b's "runs EAGERLY" promise on the reactor path; the chatroom
  program's natural spelling (spawn clients, then accept). PIN:
  `examples/spawned_task_runs_before_reactor_park.saw` (XFAIL REMOVED —
  it passes). THE DIAGNOSIS WAS NOT THE PARK: `sleep` is an intrinsic and
  `accept` is a std METHOD, and the entry compile has no effect node for a
  std method, so `main` was never wrapped in the entry executor at all and
  `accept`'s `io_wait` took the outside-frame blocking lowering. Timer vs
  reactor was a coincidence of the two spellings.
- **DF-203b (LIVENESS — CLOSED by design 206, landed via 210 Aug 11): `Channel.receive()`
  through ONE helper frame in a spawned task hangs.** Direct `ch.receive()` in the
  task body works; the same operation behind `acquire(ch)` (free function
  OR method — the extra FRAME is the trigger, isolated by a five-probe
  ladder) prints the first entry and stops. Contradicts the documented
  any-nesting-depth guarantee (96/104); suspected root is design 62 G3's
  INLINE receive lowering not composing with an embedding callee frame.
  The reusable-semaphore shape every library writes. PIN:
  `examples/channel_receive_through_helper.saw` (XFAIL REMOVED — it passes).
  THE G3 LOWERING WAS INNOCENT: the same std-method blind spot left `acquire`
  out of the driven closure entirely, so its `receive()` compiled to the
  library body, whose `yield_now` is a no-op outside a frame — a bare spin.

Both belong to ONE subsystem (executor park/drive paths) — candidate
small brief 206 alongside/ahead of 201, same surface discipline. The
rest of the wave's triage (std ergonomics batch: String→Data, File.write
overload, temp dirs, zero-pad; diagnostics batch: for-in .iter() hint +
cascade, transfer-error anchor at the read site, generic-ctor cascade;
skill/README edits: Atomic prelude line, build-and-return idiom, generic
CONSTRUCTORS excluded from inference, String.split unconfirmed-in-spec;
open probe: Vector<TaskHandle> dynamic-join spelling) lands with the
wave summary.

## The quality program — designs 190-194 (ALL LANDED Aug 9-10)

`designs/190-quality-program.md` is the analysis (findings-vs-proposals
matrix + three code censuses); 191-194 are the briefs it produced.
User-approved Aug 9, executed overnight Aug 9-10 in order (DF-190a
direct fix, then 193, 191 ∥ 192, 194), each ff-merged battery-green.
The process rules (position funnel-or-matrix; contract-flip consumer
sweep; safety-surface conformance-rows-first) live in CLAUDE.md.
NOTE for future census citations: several of 190's diagnoses were
corrected by the builds — DF-190b's cause, the spawn capture-MODE mask,
and the graft-straggler list (3 false, 5 missed) — the corrections are
recorded in the finding entries below and in 193/194's landed briefs.

**193 LANDED Aug 10** (all eight units; see `designs/193-checker-funnels.md`).
Four shared funnels exist now and each names its entry points in its docstring:
`Namespace.read_policy` (design 131's read table over design 139's tiers),
`ast_walk` (`child_nodes` / `map_nodes` / `control_blocks` + `CONTAINER_KINDS`),
`noescape.first_reference_in` (+ the `NO_ESCAPE_POSITIONS` matrix, three new
rows), and `Namespace.send_check` (+ `SEND_POSITIONS`). `sawc/visitor.py` is
deleted. Three soundness holes closed (DF-190d, DF-193b, the unchecked `spawn`
result); four findings filed (DF-193a/b/c-in-193b/d). Two census diagnoses were
wrong and are corrected in place below.

**192 LANDED Aug 10** (all five units; see
`designs/192-diagnostics-floor-and-oracles.md`). The compiler no longer has an
unwrapped stage: both typechecker dispatch fallthroughs RAISE, four dispatch
chokepoints stamp a `_current_node` breadcrumb, and every internal failure —
typechecker, codegen, or llvmlite — reports one line,
`internal compiler error at FILE:LINE:COL (<NodeType>): <message>`, with
`SAW_DEBUG=1` keeping the traceback. `tools/sawfuzz.py` fuzzes the corpus by
mutation against one oracle (succeed or diagnose cleanly), deterministic per
`(seed, index)` and wave-bounded; `tools/sawfuzz_known.txt` is its XFAIL
ledger. gmgate gained a 15-program `concurrency` lane beside the ownership one.
`tools/battery.sh` is now the tracked battery. SIX findings: DF-192a and
DF-192e fixed, DF-192b/c/d/f/g pinned (DF-192d fixed since, by design 198).
**DF-192g is a confirmed wrong answer** — below.

- **DF-190a — FIXED (pulled forward of the queue, landed Aug 9/10).**
  The typechecker now mirrors codegen's consume gate in
  `_check_match_expr`: a plain local scrutinee of an owning-tier
  (NoCopy/ExplicitCopy) enum with owning payload is marked moved, so a
  second `match s` is a clean use-after-move error. PIN flipped to a
  passing error test: `examples/match_owned_enum_double_consume.saw`.
  RESIDUAL for 193 u1: the copy-tier oracle unification note stands,
  and DF-190d (below) is the implicit-tier half of the same hole.
- **DF-190d — FIXED (design 193 unit 1).** The consume gate was
  `enum_has_owning` (any payload needs cleanup), which is not a transfer
  class, so an ImplicitCopy-tier enum's payload was released at the first
  arm's end while the scrutinee was still live. `_generate_match_expr`
  now has two modes on the scrutinee's tier: CONSUME for the owning
  tiers, RETAIN (bindings retain at extraction, scrutinee keeps
  ownership) for ImplicitCopy. Only a named non-borrowed local can be in
  retain mode — a temporary is owned by nobody and keeps consuming. The
  oracle unification landed with it: `Namespace.read_policy` is the one
  derivation of design 131's read table from design 139's tiers, named
  entry points in its docstring. PIN flipped:
  `examples/match_implicit_enum_payload_single_release.saw`.
- **DF-190b — FIXED (design 193 unit 2), and the census's root cause was
  WRONG.** The try/catch was a red herring: the failing spelling is the
  LABELED call `compute(ok: true)`, which is syntactically a struct
  literal (design 66), so it reaches the coroutine transform as a
  `StructInit` while every suspending-call classifier there tests for a
  `FunctionCall`. The call was never driven, and once the transform
  replaced the callee with its frame the leftover struct-init spelling
  had nothing to resolve against — hence ``undefined struct `compute` ``.
  The identical UNLABELED shape inside the same `try … catch` compiled
  and ran all along. Fixed by canonicalizing the spelling before any
  classifier runs (`_rewrite_labeled_calls`, beside the DF-158d yield
  rewrite) plus the sibling position at the SPAWN argument
  (`group.spawn(worker(n: 20))` was refused by the typechecker with a
  message showing the very call it was given). PINS:
  `examples/coro_try_catch_suspending.saw` (flipped),
  `examples/coro_labeled_call_positions.saw` (new, three positions).
- **DF-193b (SOUNDNESS, CONFIRMED double-free, found + FIXED by 193 u3): a
  `move` written inside a STRUCT LITERAL was invisible to the
  borrowing-match check, so a `match v[i]` arm destructured the element in
  place.** `_arm_moves_binding` decides whether an arm reads the place or
  destructures it, and its walk stopped at tuples —
  `StructInit.field_inits` being a list of `(name, value)` tuples, an arm
  body `Held(r: move r)` looked move-free. The match then lowered into a
  borrow window and the payload moved OUT of storage the vector still owned:
  probe printed `deinit 1` twice, exit 0. Now the ordinary value-read error
  naming `with_ref`/`swap_out`. The same tuple hole in the chain-assign
  exclusivity walk let `w?.c = Cell(v: refill(&var w))` past the Law while
  the shallower spelling was refused. Both walks are on the shared
  `ast_walk.child_nodes` now. PINS:
  `examples/place_match_arm_move_in_literal.saw`,
  `examples/chain_assign_exclusivity_in_literal.saw`.
- **DF-193c — FIXED by the unit that found it (193 u6): `spawn { … }`'s RESULT
  type was never `Send`-checked.** The captures were audited from the start;
  the result travels the other way (computed on the task's thread, handed back
  by `join()`) and nothing asked. `extension Task<T: Send>: UnsafeSend` was
  doing the only guarding, and it guards the wrong crossing — it stops the
  HANDLE from crossing a second boundary and says nothing about the one every
  task makes. `spawn { make_raw(&var n) }` returning a struct with an
  `UnsafePointer` field compiled and ran. Now refused at the `spawn`, with a
  type mentioning a type PARAMETER left to its instantiation. The census's
  other masked gap, capture MODE, is genuinely masked — by design 16/29 (an
  escaping closure may not borrow-capture), not by "closures are never Send" —
  and `examples/errors/capture_borrow_escaping.saw` already pins it. PIN:
  `examples/errors/spawn_result_not_send.saw`.
- **DF-194a (SPEC/IMPL, filed Aug 10 by 194 u4): a MODULE-QUALIFIED type name
  does not resolve in the three annotation slots stored RAW.** `struct Holder {
  p: dep.Point }`, `case Full(p: dep.Point)` and `type Alias = dep.Point` each
  keep the dotted spelling into type comparison, so `field `p` expects type
  `dep.Point` but got `Point``. Those three slots are read straight off the AST
  and never reach `_resolve_type`, the one place that walks a module qualifier —
  the same three unit 4 had to wire the prelude gate into by hand, which is how
  this surfaced. `_canonical_type_name` returns a dotted name unchanged ON
  PURPOSE ("for `_resolve_type`'s module-walk branch to handle") and for these
  slots that branch never runs. A fourth face: a constructor's generic ARGUMENT
  (`Vector<data.Data>()` binds a local whose element type keeps the dot).
  Pre-existing — reproduced identically on the unit-3 tree — and true for a USER
  module as well as for std. Design 150 claims outright that "a qualifier works
  in EVERY position a name appears", so this is a deviation from the spec, not a
  gap in it. It MATTERS MORE after unit 4: the gate's hint offers `import
  std.data` + `data.Data` as one of three ways to satisfy it, and that one does
  not work in a field. NOT fixed here — the fix is about what a dotted name
  canonicalizes to in a slot nothing resolves, which is a design-144 identity
  question and wants a ruling rather than a patch mid-brief. PIN:
  `examples/qualified_type_in_declaration_slot.saw` (XFAIL, cited).
- **DF-193d (SPEC/IMPL, filed Aug 10 by 193 u7 — supersedes DF-188k's "general
  fix" line with a diagnosis; CLOSED Aug 10 by 194 u4): the prelude gate cannot
  run on type ANNOTATIONS until a written-form PROVENANCE bit exists.** Building the funnel and running
  it over signature annotations refuses `func one() -> data.Data` under
  `import std.data` — the legal qualified spelling — because by the time any
  check can read the annotation, BOTH `_canonicalize_module_types` and
  `_register_function`'s design-68 write-back have replaced the author's
  spelling with the resolved identity, and a qualified `data.Data` is then
  indistinguishable from a bare unimported `Data`. (The front half also
  re-enters the same AST for the place lowering and the coroutine transform, so
  any hook must be idempotent against already-rewritten annotations.) The fix
  is a durable bit — on the annotation slot or the `SawType` — set where the
  qualifier is resolved; that is an AST-contract change and belongs with
  design 194's typed-AST work, not here. Also worth knowing before it lands:
  the corpus itself relies on the gap — `examples/cbor169_vectors.saw` names
  `IoError` in a return type with no import, and closing the gate makes that
  (and any user code like it) an error, so the landing owes a corpus sweep.
  A `static`'s annotation, the one slot nothing rewrites, stays gated (design
  188 unit 7, now through the shared `_gate_written_type`). PIN:
  `examples/std_import_gate_signature_position.saw` (XFAIL, cited).
  **CLOSED by 194 unit 4.** The bit is `SawType.written_name` (+ file/line/
  column), stamped by the parser at the one place a named type is built and
  never touched by either rewrite; the gate reads it in `_resolve_type` plus the
  three raw declaration slots, and it is exempt wherever the spelling is not a
  user's (no provenance = compiler-built; a dotted name = reached through a
  qualifier an import bound; a std source FILE = std extends itself by design).
  Design 188 unit 7's separate `static` mini-walk is retired — the funnel covers
  that position and keeping both printed the diagnostic twice. The XFAIL is
  gone; conformance rows W02-W05 carry the matrix and its two controls. Consumer
  sweep (recorded in the landing): exactly TWO offenders in the whole tree, both
  in `examples/` — `cbor169_vectors.saw` and
  `net_connect_dials_the_host_it_was_given.saw`, each naming `IoError` in a
  return type with no import, both fixed in the same landing. blade, libs,
  devtools and sos were clean.
- **DF-193a — FIXED (design 196 unit 3): a suspension inside a
  `try { … } catch { … }` BLOCK in a driven body.** The error path got its
  own states, and the shape of the answer is smaller than the finding
  feared. THE CATCH ARM IS A STATE. The try body lowers under a `_try_ctx`
  naming that state plus the frame field the caught error travels in, and
  every statement in it that holds a propagating `try` is wrapped in a
  synthesized ONE-STATEMENT `try { <it> } catch { <field> = error;
  __state = <catch>; continue }`. That wrapper is the whole trick: codegen's
  own try lowering keeps deciding where the error edge LEAVES (a `try`
  buried in an argument list, two in one expression, one inside a
  non-spanning `if`), and the landing only says where it GOES — and
  `continue` reaches the resume dispatch loop from inside a nested region,
  so the jump is a state transition rather than a branch within the state.
  Falling off either arm reaches a merge state, so the result is the same
  diamond `_split_if` builds. Everything under a split try/catch is
  frame-resident (a `let` inside the wrapper would otherwise be scoped to
  it), and the catch's implicit `error` binding now goes through
  `_uniquify_bindings` like any other name, so two catch blocks in one body
  get two fields. Value position works too, through design 120's
  value-conditional lowering (`let r = try { … } catch { … }`) and the
  tail normalization. PIN FLIPPED: `examples/coro_try_block_suspending.saw`;
  the 13-row position matrix is `examples/coro_try_block_positions.saw`.
  Three findings came out of building it, all fixed in the same landing
  (DF-196a/c/d) and one fence filed (DF-196b).

- **DF-196a — FIXED (design 196 unit 3, found while building it):
  reassigning an OWNING local across a suspension was a compile error.**
  `var out = "none"` … `yield_now()` … `out = "ok"` in any driven body.
  A frame-resident non-POD local is held as `T?` (the optional's tag is
  the drop flag), so a READ is `self.out!` — and the transform rewrote the
  assignment TARGET the same way, asking codegen to write THROUGH the `!`.
  That leaked the old payload until design 176 made `!` an illegal
  assignment target, and has been a clean error on an ordinary program
  since. A whole-binding write is a write of the FIELD: the same store an
  initializing `let` emits, which wraps to `Some` and drops what the field
  held. Only a bare whole-binding target changed — `out.f = v`, `out[i] = v`
  and a `ref`-encoded binding still reach their storage through the read.
  PIN: `examples/coro_reassign_owning_local.saw` (passing).

- **DF-196b (FENCE, filed + pinned by design 196 unit 3): a suspending
  `try { } catch { }` block may raise only ONE error type.** Two callees
  with different error types in one try body means the catch binds the
  synthesized `_CatchError_<id>` union, and each error edge has to wrap its
  concrete error into the right variant on the way to the frame field the
  split carries it in. Codegen builds that wrap for an IN-PLACE try/catch
  (`_wrap_error_in_union`); the split lowering hands the error over through
  an ordinary assignment and cannot ask for it. Refused cleanly at the
  user's `try`, naming both types and the two spellings that work (one
  block per error type, or an inline `try <call> catch { … }`). Fixing it
  means either synthesizing the union construction in the transform or
  moving the wrap somewhere the transform can reach. PIN:
  `examples/coro_try_block_two_error_types.saw` (a passing ERROR test — the
  fence is the behavior, so it is pinned by its diagnostic, not by XFAIL).

- **DF-196c — FIXED (design 196 unit 3, found while building it): an
  inline `catch` arm that DIVERGES was an ICE with an empty message.**
  `try f() catch { return E }` — the arm handles the error by leaving the
  function, so it reaches no merge and contributes no value, and codegen
  branched to the merge anyway. llvmlite asserted, and the wrapper printed
  `internal compiler error:` with nothing after it. Sync code, nothing to
  do with coroutines; the BLOCK form has guarded the same case since it was
  written. PIN: `examples/try_inline_catch_diverging_arm.saw` (passing) —
  four rows, incl. the same arm inside a suspending body and a `panic` arm.

- **DF-196d — FIXED (design 196 unit 3, found while building it): a
  propagating `try` in a body that SUSPENDS.** `let v = try inner(n)` after
  a `yield_now()` was ``` `try` cannot propagate errors from a function
  returning `__Poll` ``` — a type the author never wrote. The transform left
  the `try` alone and codegen tried to `ret` a Result out of `resume`. So
  design 92's failable-returns-Result idiom had NO concurrent spelling:
  `try!` panics, `try?` drops the cause, and an inline catch is not
  propagation. Same landing-pad shape as DF-193a's, with the landing being
  the frame's own done sequence over the wrapped error — `ResultErrWrap`
  when the callee's error type IS the function's, design 56's
  `ErasedErrWrap` when the function returns an erased `Result<T, Box<any
  Error>>` and the callee's error is a concrete conformer (the re-box at the
  propagation edge). Two DIFFERENT concrete error types on one statement's
  edge are refused cleanly (one error travels out of a frame; give each
  `try` its own statement). PIN:
  `examples/coro_try_propagate_suspending.saw` (passing) — five rows,
  including the spawned erased one.
- **DF-192a — FIXED by the unit that found it (192 u1): the checker's
  fourth wrap node had no re-check visitor.** Making
  `_check_expression`'s unknown-node fallthrough RAISE flushed exactly
  one node type out of the whole corpus: `ErasedErrWrap`. The checker
  BUILDS one (a concrete `E` on the way out of an erased-Result
  function), writes it back into the AST (`func.body.final_expr`,
  `stmt.value`), and then walks that same AST again on the design-146
  second pass — where it fell straight through the dispatch and returned
  `None`. Its three siblings (`visit_ResultOkWrap` /
  `visit_ResultErrWrap` / `visit_OptionalWrap`) all carry the re-check
  visitor for the documented reason (the coroutine transform rewrites
  identifiers inside `expr.value` into frame-field accesses that carry no
  `resolved_type`); this one never got it. Now it has the sibling body.
  Emission is byte-identical across all 14 erased-error corpus programs.
  No new pin: every erased-Result example in the corpus is one, since the
  fallthrough now raises rather than skipping.
- **DF-192b — FIXED (design 196 unit 2): spawning a function that returns
  an erased `Result<T, Box<any Error>>` was a codegen ICE.**
  `group.spawn(fail(7))` where `fail -> Result<Int, Box<any Error>>` died
  filling the result cell's vtable — `_get_vtable_thunk` looked up
  `__ResultCell$1$Result$2$Int$Box$2$$Any$Error$GlobalAllocator___carries_result`
  and the body was never emitted, because the cell had monomorphized under
  the arity-1 `Box$1$$Any$Error` spelling `_canonicalize_type_kind` gives
  an erased box. Two names for one type, and the vtable path was the one
  that had never been canonicalized. THE FIX IS A FUNNEL, not a patch of
  that lookup: `_erased_identity` is now the single canonical spelling an
  erasure derives every identity from, and its docstring names its two
  entry points — `_get_or_emit_vtable` (which covers the dtor, the thunks
  and the size/align header it fills) and `_type_id_for` (BOTH sides of a
  downcast). The downcast side had the same latent split: `e.is<Vector<Int>>()`
  hashed the as-written name while the vtable baked in the defaulted one.
  Pre-dated design 192 (probe-confirmed against e4761ef). PIN FLIPPED:
  `examples/erased_error_spawned_task.saw`; second row added,
  `examples/erased_error_spawned_container_result.saw` (a defaulted type
  arg at both nesting levels, plus the downcast).
- **DF-192c — FIXED (design 196 unit 1): an erased-error return in a
  SUSPENDING body was a codegen ICE.** `yield_now()` ahead of `return
  MyErr(...)` in an erased-Result function makes the body a state machine,
  so the coroutine transform lowers the return into an ASSIGNMENT into the
  frame's result slot — and codegen's `visit_ErasedErrWrap` finished
  through `_create_result_err_for_return`, which reads the ENCLOSING
  function's return type and raised `Cannot create Result.Err outside
  Result-returning function`. `ResultErrWrap` survives the same move
  because it carries its own `result_type` and passes it down; the erased
  wrap called the one-argument overload. The fix is the sibling's
  argument — one line, and the two wraps now read identically. Pre-dated
  design 192 (probe-confirmed against e4761ef). PIN FLIPPED:
  `examples/erased_error_across_suspension.saw`.
- **DF-192d — FIXED (design 198 unit 1).** A `match` with two arms for one
  enum case was an LLVM-level internal compiler error: it lowered to a
  `switch` carrying the same case value twice and llvmlite refused the
  module (`duplicate case value in switch`), while the SIBLING spelling —
  a duplicated LITERAL arm — compiled and silently took the first, because
  that lowering is a compare chain. RULED Aug 10: an EXACT duplicate arm —
  enum variant or literal — is a clean error naming both arms, and
  ranges/guards keep first-match-wins (overlap there is legitimate and
  documented). The deciding fact: a switch has no arm order, so first-wins
  was never the enum spelling's semantics — there was nothing to be
  consistent with, only a crash to replace. One chokepoint,
  `_check_duplicate_match_arms`, called before `_check_match_expr` picks a
  lowering, so both arm-checking entry points are covered by one rule.
  PINS: `examples/match_duplicate_enum_arm.saw` (flipped to a passing error
  test, still holding both spellings so they cannot drift apart again),
  `examples/match_duplicate_arm_spellings.saw` (the eight-row reject
  matrix), `examples/match_arm_overlap_legal.saw` (the accept side).
  The ledger entry left `tools/sawfuzz_known.txt` in the same landing.
  Its discovery also closed a
  unit-2 gap: `emit_ir` / `compile_to_object` run AFTER `run_codegen`
  returns and were outside every wrapper, so an IR module llvmlite refuses
  printed a raw traceback — `_run_llvm` now wraps both.
- **DF-198a (ICE, filed Aug 10 by 198 u1's probes): a guarded match over an
  enum whose cases ALL carry no payload is a codegen ICE.** A guard routes the
  match to the general pattern path, whose `_match_enum_pattern`
  (codegen/match.py) reads the tag with `extract_value(value, 0)` — the
  `{tag, payload}` shape. An all-payload-free enum lowers to a bare `i32`, so
  the read dies with `internal compiler error at FILE:L:C (MatchExpr): Can't
  index at [0] in i32`. A TUPLE scrutinee reaches the same line
  (`match (c, n) { case (Red, 0) -> ... }`), and adding a payload to any case
  of the enum makes both spellings work — which is why
  `examples/match_enum_guard.saw` (a `Slot` with a payload variant) never
  caught it. The classic switch path reads the tag correctly, so this is the
  general path missing the shape its sibling handles: design 190's duplication
  family again. Confirmed pre-existing (probed against the pre-198 compiler).
  Out of design 198's subject (duplicate arms), which is why it is filed
  rather than fixed. PIN:
  `examples/match_guard_on_payload_free_enum.saw` (XFAIL, cited).
- **DF-200a (over-rejection, filed Aug 10 by design 200 unit 1's rows): the
  `&var self.<field>` PROJECTION rule reads the lvalue SYNTACTICALLY, so it
  refuses a heap-reaching path the assignment rule accepts.** In a `&self`
  method, `self.rows[0][2] = 55` compiles and writes the caller's element (row
  M32 — `_writes_into_self_storage` walks TYPES and stops at the `Vector`
  indirection), while `f(&var self.rows[0][2])` is refused: the projection check
  in `_check_reference_expr` uses `_projects_from_self`, a purely syntactic
  walk that answers "inside the receiver" for anything rooted at `self`.
  One storage, two answers — design 190's duplication family, one rule with two
  implementations. Conservative (a refusal, never a silent write), which is why
  it is filed rather than fixed: aligning them RELAXES a safety refusal, so it
  wants a ruling rather than a drive-by. The write shapes are pinned either way
  by `examples/conformance/M32_shared_self_place_window_heap_field.saw`, whose
  header names this finding.
  **RULED Aug 10 (check-in): ALIGN — the projection rule adopts the same
  type-walking inline test (heap-reaching paths accepted, their
  assignment twin already legal; parameter-only refs can't escape the
  call), inline paths keep the refusal with a CORRECTED message (the
  current one claims "the write would be lost", false for heap paths).
  Small fix; ride the next typechecker fix batch, not its own brief.**
- **DF-192e — FIXED by the unit that found it (192 u3): a hex const generic
  argument was an uncaught parser crash.** `FixedBuf<0x10>()` died in
  `parse_const_expr`'s primary with `ValueError: invalid literal for int()
  with base 10: '0x10'` — no location, no message, a raw Python traceback.
  This is DF-185a at the SECOND hand-rolled site: design 185 routed the enum
  raw value through the shared decoder and left the const-expression grammar
  calling `int()` on an INT token's canonical text. Exactly design 190's
  duplication family — one rule, two implementations, the fix to the first
  never reaching the second — and, as with DF-185a, the notation that died is
  the one the feature exists for (a buffer or mask size is written in hex).
  Every notation design 50 defines works now, in the const-generic ARGUMENT
  and the const-parameter DEFAULT, the two positions that grammar serves. NO
  SPEC CHANGE OWED: LANGUAGE_SPEC's const-evaluator section already lists
  "integer and `Bool` literals, in every notation (`0xFF`, `0b1010`, `0o755`,
  `1_000_000`)" for "everywhere a constant is required — … a const generic
  argument", so this was documented-and-unimplemented the whole time, which
  is the one thing neither the suite nor a reader could see.
  PIN: `examples/const_generic_arg_notations.saw`.
- **DF-192f (ICE, filed Aug 10 by 192 u3): nothing checks that two integer
  operands agree on WIDTH, so a suffixed literal in a platform-`Int` context
  is a codegen ICE.** `n * 2i16` on an `Int n` is `internal compiler error at
  FILE:L:C (BinaryOp): Type of #2 arg mismatch: i64 != i16`; the same
  mismatch through an optional-binding value arm is `(AssignStatement):
  cannot store {i64, i64} to {i16, i16}*`. A suffixed literal is exact-typed
  (design 53 — the width-adopting rule is for a BARE literal) and Saw has no
  implicit integer conversion (design 170), so this is a plain type
  disagreement the checker should name. PIN:
  `examples/binop_mixed_width_operands.saw` (XFAIL, cited).
  **FIXED by design 195 unit 2** (all typed operands of an operation must be
  the same type; only bare literals promote). The ruling discussion's probe
  also found the SIGNEDNESS face — `i + u` (`Int` + `UInt`, same width)
  compiled SILENTLY and took SIGNED division — and it went through the same
  funnel. PIN flipped to a passing error test; both DF-192f signatures
  deleted from `tools/sawfuzz_known.txt`, which now holds one entry.
- **DF-192g (SOUNDNESS — CONFIRMED WRONG ANSWER, filed Aug 10 by 192 u3): a
  value `if` whose arms have different integer widths returns the WRONG
  ARM'S VALUE.** `func f(a: Int) -> Int { if a > 0 { 11 } else { 7i16 } }`
  compiles clean and `f(-3)` prints `11` — the then-arm's value on the path
  that took the else arm. The same program with a bare `7` prints `7`. No
  warning, no panic, exit 0. Same root as DF-192f (nothing checks integer
  width agreement) and the more serious face of it: the binop shape is loud,
  this one is silent. Reached by minimizing a fuzzer ICE. PIN:
  `examples/if_value_mismatched_width_arms.saw` (XFAIL, cited).
  **FIXED by design 195 unit 3** (value-branch arms are TRANSFERS — each arm
  merges against the reconciled type, so a same-sign widenable arm is LEGAL).
  PIN re-authored to EXPECT: success printing 11 then 7, the flip its own
  comment named. The finding reached two positions its entry did not name —
  a `match` arm and a `??` operand, where a CONSTANT narrow arm answered
  correctly BY ACCIDENT (LLVM's textual `phi` gives an incoming constant no
  type of its own) and a VARIABLE one was an ICE — and those are closed too.
  **UNIT-1 PROBE ADDENDUM (design 195, Aug 10).** Probing the twelve matrix
  rows found the finding reaches SIX positions the two entries above did not
  name, all one root: comparison mixed-width (an LLVM-level ICE) and
  comparison sign-mix (silent, signed compare on an unsigned operand);
  `&+ &- &*` mixed (ICE); COMPOUND ASSIGNMENT `a += b16` (ICE) and the
  BITWISE `& | ^` (silent — the right operand was ZERO-extended whatever its
  signedness, so a negative narrow operand masked against the wrong word),
  neither of which the brief's matrix carried; and the NEGATED bare literal
  `n * -2`, which is an adoption spelling (row 12) that the width rule never
  reached and which ICEd. Rows 9 and 10 (`match` arms, `??`) were RIGHT BY
  ACCIDENT for a constant arm — LLVM's textual `phi` prints an incoming
  constant with no type of its own, so an `i16` 7 was re-read as an `i64` 7 —
  and an ICE the moment the arm was a variable. Range bounds (row 11) and a
  narrowing `if` arm (row 8's first half) were already clean rejections. Rows
  W06-W19 of `examples/conformance/INDEX.md` carry all of it.
- **DF-195a (SOUNDNESS — WRONG ANSWER, filed Aug 10 by 195 u1's probes): an
  implicit LOSSLESS widening at a transfer extends by the TARGET's
  signedness, so an unsigned source SIGN-extends.** `let u: UInt32 =
  4000000000u32` followed by `let wide: Int = u` prints `-294967296`, and the
  same value through a `return` does too. LANGUAGE_SPEC's conversion cost
  table says the pair emits "one `zext`"; the extension is picked off the
  target instead, which is right for every signed source and wrong for every
  unsigned one. Load-bearing for design 195 rule 2: a value-branch arm is a
  transfer whose lossless widening is legal, so the widening has to be
  correct before arms can ride it. PIN:
  `examples/int_widening_transfer_preserves_unsigned.saw`.
  **FIXED by design 195 unit 3.** `_widen_int_value` is the one funnel now,
  extending by the SOURCE's signedness, its docstring listing every position
  an implicit widening happens. Fixed at `let`, `return` and a struct FIELD
  (each has the source expression in hand) and at the value-branch arms
  (through the synthesized cast rule 2 inserts). PIN flipped to a passing
  test — re-authored on the way, because its third case asserted a `UInt8`
  into an `Int16`, which design 53 refuses at a transfer whether or not the
  pair is lossless. RESIDUAL: DF-195e.
- **DF-195e (SOUNDNESS, residual of DF-195a, filed Aug 10 by 195 u3): two
  implicit-widening positions still extend by SIGNED, because no source type
  reaches them.** `_coerce_call_args` and the fixed-array element-assignment
  path hold LLVM values with no source EXPRESSION threaded to them, so
  `f(u32val)` into an `Int` parameter, and a store of an unsigned value into
  a wider signed element, still sign-extend and answer negative. Same root
  and same fix shape as DF-195a — thread the argument/element expression to
  `_widen_int_value`, which already takes the type — and mechanical rather
  than hard; left out of design 195 because `_coerce_call_args` has nine call
  sites and the brief's own subject was operand agreement. The funnel's
  docstring NAMES both positions, so the next reader of the rule finds them
  without a census. PIN:
  `examples/int_widening_call_argument.saw` (XFAIL, cited).
- **DF-195b (SOUNDNESS + a RULING OWED, filed Aug 10 by 195 u1's probes): a
  NARROWING transfer through a platform `Int` truncates silently.**
  `let n: Int = 300` followed by `let b: Int8 = n` prints `44`. Design 170
  made every narrowing written (`as` panics, `from` answers `None`,
  `from(truncating:)` wraps); `_types_compatible` admits a platform
  `Int`/`UInt` into ANY integer type and bypasses all three. The permission
  exists so a bare LITERAL can adopt a fixed-width slot, a job design 87's
  expected-type propagation does properly now — so what it covers today is a
  runtime value losing its high bits. Between two FIXED widths the same
  transfer is already a clean error, so the hole is exactly the platform pair.
  DELIBERATELY OUT of design 195 (operand agreement, not conversion): closing
  it is a behavioral flip owing its own consumer sweep, and it belongs with
  design 170's rules. PIN:
  `examples/int_narrowing_transfer_through_platform_int.saw` (XFAIL, cited).
  **RULED Aug 10 (check-in): both axes become ERRORS naming design 170's
  three conversion spellings — the transfer-position twin of 195's
  operand rule. Own brief (205, to author) with its consumer sweep;
  bare-literal adoption stays untouched.**
- **DF-195c (SOUNDNESS + a RULING OWED, filed Aug 10 by 195 u1's probes): a
  same-width SIGN-FLIPPING transfer through the platform pair reinterprets
  silently.** `let u: UInt = UInt.max` followed by `let i: Int = u` prints
  `-1`. The other axis of DF-195b, from the same `_types_compatible` arm, and
  the one design 170 checks hardest at a written cast (`-1 as UInt8` panics).
  Design 195 rule 1 closes the OPERATOR face (`i + u` is refused now); the
  transfer face rides with DF-195b. PIN:
  `examples/int_sign_flip_transfer_through_platform_int.saw` (XFAIL, cited).
- **DF-195d (ICE + a RULING OWED, filed Aug 10 by 195 u1's probes): mixing a
  `Float` and an integer operand is an internal compiler error.** The
  arithmetic arm answers `Float` for a mixed pair, promising a promotion the
  lowering does not implement: `a + f` dies with `Type of #2 arg mismatch:
  i64 != double` and `f + 1` with `Operands must be the same type, got
  (double, i64)`. Design 195 unit 2's funnel makes the first a clean error —
  `Int` and `Float` are two types, which is rule 1 exactly. THE OPEN
  QUESTION is the second: `f + 1` is a BARE literal beside a `Float`, and
  rule 1's own carve-out is that a bare literal adopts. Whether an INTEGER
  literal may adopt `Float` is a language question design 195 explicitly did
  not take ("float/integer mixing" is in its Explicitly out list), so both
  spellings are refused for now and the error hints at `1.0`. PIN:
  `examples/float_integer_operand_mix.saw` (XFAIL until 195 u2, then a
  passing error test).
  **RULED Aug 10 (check-in): NO adoption — an integer literal does not
  adopt `Float` (Saw has no integer→float conversion anywhere else;
  `1.0` is the spelling). The landed error + hint IS the ruled
  behavior; DF-195d CLOSES with no further work.**
- **DF-190c (VERIFY / latent must-agree, filed Aug 9, CLOSED Aug 10 by 194 u2):
  `_make_specialization_key` had DIVERGED** — codegen handled design-148
  const-value type args, the typechecker dropped them to an empty key.
  PROBE ANSWER: no, a const-generic specialization never keys through the
  typechecker copy — over the whole corpus it saw a `CONST_VALUE` argument
  zero times in 219,689 calls, and codegen's 24 const keys matched no
  registered entry either. The reason is upstream of both: a const-generic
  SPECIALIZATION cannot be written at all (`extension Ring<4>` is the parse
  error "Expected type parameter name"), so no const key is ever registered.
  Latent, never live. Both copies now delegate to one
  `ast_nodes.specialization_key`; PIN:
  `examples/const_generic_specialized_extension_unsupported.saw` (an ordinary
  expectation test — nothing is broken, and the pin flips the day the grammar
  admits a const specialization).

**194 LANDED Aug 10** (all five units; see `designs/194-contract-debt.md`). The
AST contract is declared and GATED: `tools/test_ast_graft.py` (battery lane
`astgraft`, `make astgraft`) fails on any attribute assignment in `sawc/` that
no class declares, which is design 126's own exit criterion mechanized after
five years of nobody checking it — twelve grafts had crept back, six of them
past the census. Two must-agree helper pairs deduplicated
(`ast_nodes.specialization_key`, `target_info.pointer_size_bits`) and a third
triple (`ast_walk.pattern_binding_sites`). The prelude gate runs on ANNOTATIONS
now, through one funnel over a parser-stamped written-form provenance bit
(`SawType.written_name`), closing DF-188k and DF-193d. 162 of codegen's 209
AST-field `getattr`s are direct typed reads; the 47 that remain are guards, each
named in its batch's commit. ONE finding filed (DF-194a below); two bugs fixed
on the way — the never-installed `static_globals` mangled key, and a
negative-array-length diagnostic that would have crashed on the path where the
length carries no expression, which is the first true positive Pyright could see
once the reads stopped being `Any`.

**191 LANDED Aug 10** (all five units; see `designs/191-conformance-suite.md`).
The Aug-8 audit's 247 rows are a standing suite: `examples/conformance/`, one
file per row that needed one, `examples/conformance/INDEX.md` naming the
covering test for every row that did not, and `-f conformance/` as the subset
switch. 54 rows ported, 193 deduped to existing pins — a higher dedup rate
than the census predicted, because designs 188/189/193 landed fifteen pins
straight out of this audit between the census and the port. Twelve rows were
re-authored to a RULING rather than to the audit's guess (listed in the INDEX's
"re-authored" column); one finding filed.

- **DF-191a — FIXED (design 196 unit 4): a `Mutex.lock` body that CAPTURES a
  frame-resident local of the DRIVEN function.** The rule was already right and
  its POSITIONS were not. A closure literal in a driven body captures frame
  locals through `let <name> = self.<name>.copy()` bindings the transform
  materializes AHEAD of it, and only three positions installed the accumulator
  that collects them (a `let`, an assignment, a bare expression statement).
  Everywhere else `_cap_lets` was None and the closure was refused. Now
  `_rewrite_hosting` is the ONE funnel, and its docstring names its entries: the
  body's tail (K13's own shape), a `return`, a destructuring `let`, the
  conditions/scrutinees of an in-place AND a CFG-split `if`/`match`/`if let`/
  `guard let`, a nested block's tail, a `for`'s range bounds, a nested
  suspending call's arguments, and an offloaded blocking extern's arguments. The
  one position that genuinely cannot host a statement — a bare (non-block) match
  arm expression — keeps its clean refusal, as does a `while` CONDITION (a
  capture materialized there would run once, ahead of a condition that runs
  every iteration). PIN FLIPPED: `examples/conformance/K13_mt_sum_under_mutex.saw`
  (+ its INDEX row, and the row now asserts the SUM rather than only compiling);
  the 12-row position matrix is `examples/coro_closure_capture_positions.saw`.
  Two more findings came out of it, both fixed in the same landing:

- **DF-196e — FIXED (design 196 unit 4, found while building it): two closures
  in one block capturing the SAME frame local collided.** Each materialization
  declared `let n = self.n.copy()` under the frame local's own name, so the
  second was ``variable `n` is already defined in this scope`` — and the first
  closure's `move` capture had consumed it anyway. The materialized local takes
  a FRESH name per closure now (`__capN_<name>`), and the closure is renamed
  onto it; a user-WRITTEN capture spec keeps its own name and its own meaning.
  Covered by row 5 of the position matrix.

- **DF-196f — FIXED (design 196 unit 4, found while building it): a
  suspension-spanning `match` whose arm PATTERN binds the SCRUTINEE lost the
  binding.** The frame fields for a spanning match came from the enum's variant
  PAYLOAD types, so a design-63 pattern binding the scrutinee itself — the
  catch-all `case v ->`, a tuple pattern over a tuple scrutinee, a catch-all
  over an enum — got no field, and the arm body (a separate state) read
  ``undefined variable `v``` on a legal program. `_scrutinee_binding_types` is
  the complement, permissive about the literals and ranges an arm may hold
  beside its bindings. PIN: `examples/coro_match_binds_scrutinee.saw` (passing).

- **DF-191a (ORIGINAL REPORT, filed Aug 10 by 191 u1): a `Mutex.lock` body that
  CAPTURES a frame-resident local of the DRIVEN function is refused, and the
  diagnostic's suggested workaround does not typecheck.** Conformance row K13 —
  an MT group accumulating a per-task amount into a shared `Arc<Mutex<Int>>`,
  which is the documented way to share mutable state across worker threads:
  ```saw
  func add(shared: Arc<Mutex<Int>>, n: Int) -> Int {
      shared.lock({ &var c in c = c + n  c })   // captures `n`
  }
  // group.spawn(add(shared.copy(), 1))
  // error: coroutine transform: a closure capturing a frame-resident local in
  //   this position of driven `add` is not supported; bind the closure to a
  //   `let` in straight-line body code
  ```
  The identical body with NOTHING captured (`c = c + 1`) compiles and runs, and
  so does the whole-body-in-`main` shape `examples/mutex_counter.saw` pins — so
  what the transform cannot do is specifically a capturing closure in an
  argument position of a driven body. The hint is unreachable here on top of
  that: binding the closure to a `let` first trips `Mutex.lock`'s `sync`
  requirement (``pass a `sync`-typed function value or a closure literal that is
  checked suspension-free``), so the two rules leave no spelling. Either the
  transform learns this position or the hint has to name a shape that works.
  Not a soundness issue — a clean compile error — but it blocks the canonical
  shared-counter idiom from a spawned task. PIN:
  `examples/conformance/K13_mt_sum_under_mutex.saw` (XFAIL, cited).

## Design 186 — `UnsafeMutableInterior` (ALL EIGHT UNITS LANDED, Aug 9)

`designs/186-unsafe-mutable-interior.md`. Interior mutability is a PROPERTY
now, not three names the compiler knows. Seven commits, the full suite green at
each. **Both name lists dissolved**: `namespace.py:_send_sync`'s Send/Sync
override list (`Arc`/`Mutex`/`Channel`/`Task`/`SpinLock`/`UnsafeMemory`/
`ReadOnly`/`WriteOnly`/`Vector`/`Map`/`Set`/`Data`/`StringBuilder`) and
`statements.py:_INTERIOR_MUTABLE_TYPES`. One pin flipped and was renamed
(`static_const_expr_init`, DF-185b).

Two of the migration's entries needed no replacement at all, which is the thing
a name list can never tell you: `UnsafeMemory` is a struct of one `Int` and
DERIVES both markers, and `ReadOnly`/`WriteOnly` derive from the inner type that
is literally their only field. `Map`, `Set` and `Data` derive through the
declarations on `Vector`, `Vector` and `DataBuf`+`Arc` respectively. The
interior-mutability EXEMPTION dissolved to nothing: every call it existed for is
a `&self` method the 176b rule never refused.

- **DF-186a — CLOSED by design 202: `Atomic` is move-only.**
  `extension Atomic<T>: NoCopy {}` in builtin.saw, on the spelling
  `SpinLock`/`Once`/`Mutex` already use. `NoCopy` and deliberately not
  `NoMove` — nothing pins an atomic's address, and statics are
  unaffected either way. The design-186 cell clause is UNTOUCHED and
  needed no code: `member_copy_tier` fires on the CELL ITSELF, and it
  reaches `copy_tier`, which consults `declared_copy_tier` before any
  structural join — so a declared policy on the field's own type wins,
  and `Atomic<Int>` cascades `NoCopy` upward while an undeclared
  `struct C { cell: UnsafeMutableInterior<Int> }` stays free-tier. Both
  directions pinned by `examples/atomic_nocopy_cell_clause.saw`; the
  refusals by conformance rows V26/V27, the three controls by V28-V30.
  THE FLUSH LIST matched the census exactly — five holders, nothing
  else in 1723 tests: `SlabHead` (std/slab.saw), `Job`
  (rt/common/offload.saw), and `Counter`/`Pair`/`Tagged<T>`,
  `Counter`, `Stats` in the three example files. Zero call sites needed
  a `move` or a `.copy()`; zero tests changed their expected output.
  Original entry follows.
  Should
  `Atomic<T>` be move-only? The cell is `NoCopy` as ruled, and a cell FIELD
  contributes its `T`'s copy class rather than cascading `NoCopy` onto its
  container (stated once in `Namespace.member_copy_tier`). Without that clause
  `Atomic<Int>` would become `NoCopy`, and with it every struct holding one —
  measured: std's `SlabHead` first, then the world. Rust agrees with the
  cascade (`AtomicUsize` is `!Copy`), so the question is real; it is a separate
  decision with its own migration and design 186 does not open it. What the
  clause costs today: a user `Cell<T>` wrapper is bitwise-copyable unless its
  author writes `extension Cell<T>: NoCopy {}`, which the wrapper idiom in the
  skill and the spec both say to do. Copying an `Atomic` has been legal and
  equally footgun-shaped since design 41.
- **DF-186b — CLOSED (unit 3), PRE-EXISTING.** A `static` of a GENERIC struct
  initialized by a const struct literal was `internal compiler error: 'Wrap'`.
  `_const_from_expr` looked the layout up under the TEMPLATE name, which the
  monomorphization table has never heard of, and the bare `KeyError` surfaced as
  an ICE. The non-generic form always worked, which is why it went unnoticed:
  design 41's const-init statics predate generic statics by a long way. Pin:
  `examples/static_generic_struct_const_init.saw`.
- **DF-186c — OPEN (two language gaps, one C body).** The Linux half of the
  one-word lock (`__saw_rt_lock_acquire`/`_release`) is a futex, and it lives in
  `rt/shim.c` rather than in `rt/host_linux/` because a futex needs two things
  Saw has not got: ATOMICS ON A 32-BIT WORD REACHED THROUGH A POINTER
  (`Atomic<T>` is `Atomic<Int>` in v1, and has no spelling for "atomically
  operate on this pointee"), and a VARIADIC extern (glibc's is `long syscall(long,
  ...)`, the same DF-113c gap `fcntl` sits in). Either feature shrinks the body
  back to Saw. The macOS half IS Saw (`rt/host_macos/lock.saw`, two
  `os_unfair_lock` calls). **The Linux half is UNEXECUTED**: this host is macOS,
  so it is reviewed C, not tested C — the first Linux run of the suite is what
  proves it, and `mutex_static_contention_mt` is the test that would catch it.
- **DF-186d — CLOSED (unit 5), PRE-EXISTING.** `Arc`/`Box` payload-method
  forwarding loaded the payload BY VALUE unconditionally, which is wrong the
  moment a payload's `&self` arrives by pointer. `Arc<SpinLock<Int>>.lock(...)`
  already had that shape before design 186 and ICE'd on the arity mismatch; the
  inline `Mutex` made it the common case (`mutex_counter` is
  `Arc<Mutex<Int>>`). Both forwards read the convention off the callee's emitted
  signature now. Had it type-checked instead of ICE'ing it would have been far
  worse than a crash: every thread would have locked its own copy of the mutex
  and all of them would have succeeded at once.

## Design 188 — safety-audit batch (ALL EIGHT UNITS LANDED, Aug 9)

Source: the Aug-8 external review (`review.md`) + systematic audit
(`safety_audit.md`, 247 rows, probes in `.build/scratch/safety/` —
GITIGNORED, which is why the load-bearing repros are promoted to example
pins below). Nine findings, all closed. All four rulings were ratified in the
Aug-9 one-by-one review — the brief's units 2-5 record each decision and the
alternatives explored and declined. D-numbers cite the audit's sections. Eight
per-unit commits, the full suite green at each; eight pins flipped
(`enum_ref_payload_escape`, `typealias_ref_launder`, `place_window_exclusivity`,
`lend_accessor_local`, `taskgroup_move_live`, `spawn_capture_after_group`,
`unsafe_trait_requirement_effect`, `spinlock_import_gate`). Two follow-on
findings filed below (DF-188j, DF-188k).

- **DF-188a — CLOSED (unit 1).** An enum case payload could be a reference.
  Design 163d enumerated the positions that carry a reference past its call and
  enum payloads were not among them, so a one-case enum was a general bypass:
  `case Held(r: &Int)` accepted, `Slot.Held(r: &x)` filled from an ordinary `&`
  parameter, the value into `Vector` storage outliving the call. Cause: the
  NAMES walk simply had no call at the payload position — `parse_enum` never
  invoked it. Fixed with the field position's own walk and diagnostic. Pin
  flipped: `examples/enum_ref_payload_escape.saw`.
- **DF-188b — CLOSED (unit 1).** A `type` alias laundered a reference into every
  guarded position. Cause: all four written-form checks live in the PARSER,
  which is where the position is known and where no alias can be resolved yet,
  so `type R = &Int` read as a plain named type. Fixed by re-running the walk in
  the typechecker with aliases RESOLVED at every step, over the same declared
  positions plus binding annotations, and by refusing the back-conversion
  `R(&x)` that inhabits them. A PARAMETER stays legal — the walk never ran
  there. Pin flipped: `examples/typealias_ref_launder.saw`; the audit's other
  two alias positions are `examples/errors/typealias_ref_{generic_argument,
  construction}.saw` and the boundary is `examples/ref_no_escape_alias_boundary.saw`.
- **DF-188c — CLOSED (unit 5).** Case (i), the probe-confirmed silent UAF: a
  reference capture of a binding declared AFTER its group. Cause: nothing
  related a capture to its group's declaration order, and the soundness argument
  for captures is entirely that order — LIFO runs the later binding's deinit
  before the group joins. Now an error naming the binding, the group, both
  lines, the LIFO order and the fix. Case (ii) probed ALREADY REFUSED (a closure
  is not `Send`), pinned as `examples/errors/spawn_capture_mt_send.saw`. Case
  (iii) untouched and pinned as legal:
  `examples/spawn_capture_declared_before.saw`. Join-at-the-brace was declined
  (it deadlocks the drop-to-terminate idioms). Pin flipped:
  `examples/spawn_capture_after_group.saw`. Design 189 owns the extent rule.
- **DF-188d — CLOSED (unit 4).** `move group` with a live task was accepted and
  the runtime aborted. Cause: design 124 defines a group as a scope and the type
  system had no way to say so — every relocation rule the language had was about
  DUPLICATION. `NoMove` is the missing axis: a declarable empty marker that
  REQUIRES a declared `NoCopy` (never implies it), permits exactly one move
  (constructor into binding), leaves whole-referent replacement through `&var`
  legal, cascades by DECLARATION into containing types, and is not a generic
  bound. `TaskGroup` conforms and the refused-move diagnostic cites design 124.
  `NoMove + ExplicitCopy` opens later by relaxing one check. Pin flipped:
  `examples/taskgroup_move_live.saw`.
- **DF-188e — CLOSED (design 187 unit 6).** `n += 1` on a `&var` param after
  a suspension ICEd with "Unsupported container expression in compound
  assignment" while `n = n + 1` worked. Not the transform: it makes a
  reference param a frame-resident POINTER, so the target arrives as
  `self.n[0]` — an ArrayIndex over a MemberAccess — and CODEGEN's compound
  path had no case for a non-Identifier container, which the plain assignment
  path had handled for a long while. The two are mirrored now, minus the
  ownership bookkeeping a numeric target does not need. Pin flipped:
  `examples/coro_ref_param_compound_assign.saw`, grown to the whole integer
  operator family, a Float, and a field of a `&var` referent.
- **DF-188f — CLOSED (unit 2), the headline.** Two by-reference accesses to one
  root in one call, at least one a place, silently lost writes; std `Data`
  corrupted. Cause: `_build_access_path` treated a place use as an ordinary
  projection or as nothing at all, so window roots never entered the
  path-disjointness check — and what refused the shape on ExplicitCopy/NoCopy
  receivers was the COPY POLICY (the compiler copied the receiver to open the
  second access and reported that copy), which is why a free-copy receiver sailed
  through. Fixed by charging a place use's RECEIVER whole, giving the exclusivity
  diagnostic on every tier, and — since a window's extent is the whole call —
  collecting references created by NESTED calls in the same argument list when a
  window is open (audit X31). Pin flipped: `examples/place_window_exclusivity.saw`;
  twins at `examples/errors/place_window_{data_corruption,beside_var_root}.saw`;
  the audit's correct-shapes table is `examples/place_window_exclusivity_boundary.saw`.
- **DF-188g — CLOSED (unit 3).** A `borrows` accessor could lend its own local or
  parameter; reads were sound (the frame is alive for the window) and writes
  vanished. Cause: the rule existed for a match-arm payload ("a value the body
  just BUILT dies with the accessor") and was never applied to a plain `lend`.
  Fixed in the NARROW ruled form — an accessor's parameter is refused too, `&var`
  included. Two things stay rooted without being written `self.…`: a match-arm
  payload of a receiver-rooted scrutinee, and an INDIRECTION out of the receiver
  (`lend buf[i]` for a `buf` bound from `self.buffer`), which is how std
  Vector/Data are written. Pin flipped: `examples/lend_accessor_local.saw`;
  parameter twin at `examples/errors/lend_accessor_param.saw`; accept side at
  `examples/lend_rooted_in_receiver.saw`.
- **DF-188h — CLOSED (unit 6).** The documented direction is enforced: a
  conformer of an `unsafe` trait requirement must declare the effect. Cause: the
  conformance check compared receiver mutability, return type and parameter
  count, and had never been given the effect. The reverse direction stays legal
  as rule 7's redundant declaration. Pin flipped:
  `examples/unsafe_trait_requirement_effect.saw`; accept side at
  `examples/unsafe_conformance_effects.saw` (audit row U26 is deliberately
  superseded — it was an accept row only because the rule was unenforced).
- **DF-188i — CLOSED (unit 7).** `spinlock` and `slab` joined
  `IMPORT_REQUIRED_STD_MODULES`. Cause: the allowlist and the spec's module table
  were two independent lists, so a module documented as gated and never added
  stayed bare. `tools/test_prelude_gate_doc.py` (`make preludegate`) walks the
  table and asserts the two agree in both directions. Flipping the pin surfaced a
  second half: a gated module is not compiled in at all, so `static LOCK:
  SpinLock<Int>` — which never names the type in an expression — reached codegen
  and ICEd there; the gate now runs at a static's declaration too. Pin flipped:
  `examples/spinlock_import_gate.saw`. DF-138c closed with it.
- **DF-188j (SOUNDNESS-CONTRACT, filed Aug 9 by unit 2): the Law of Exclusivity
  does not see a reference created by a NESTED call.** `sink(&var p.a,
  reset(&var p))` compiles with no place involved anywhere, and the answer
  depends on argument evaluation order (probed: `a=107 b=200`). Unit 2 closed the
  half where a window is open, because a window's extent is provably the whole
  call; the general case is a question about when an argument's borrow starts,
  which the Law has never had to answer and which no current spelling forces.
  Widening it would reject `f(&var x, g(&y))` shapes that are legal today, so it
  wants a ruling rather than a patch. Repro: `.build/scratch/p_nested_ref.saw`
  (three statements; the shape is in this entry).
  **RULED Aug 10, owned by design 199:** a nested call's by-ref
  arguments JOIN the outer call's access set — OVERLAPPING roots error
  on every tier (mirroring the landed place rule), disjoint roots stay
  legal (`f(&var x, g(&y))` compiles; the earlier "would reject" framing
  conflated the two). Consumer sweep before the flip, per rule 2.
  **CLOSED Aug 10 by design 199 unit 3.** The nested-reference collection
  design 188 unit 2 had gated on a place being present is unconditional
  now: every `&`/`&var` written strictly below an argument joins the
  access set with its own path root and meets the SAME overlap test, so
  disjoint paths are untouched and the widening is to the set alone. The
  brief's units 1-2 answered the two open questions ahead of the change —
  the receiver-position variant is NOT already caught (`p.total(reset(&var
  p))` compiled and read the receiver at its pre-reset value), and the
  consumer sweep over all 1890 tracked `.saw` files found ZERO offenders,
  so the rule landed with no grandfathering and no existing program
  changed. Pins: `examples/conformance/X41_nested_call_ref_overlaps_
  sibling.saw` (the repro in this entry), `X44_…_receiver.saw`,
  `X45_two_nested_calls_one_root.saw`; accept sides at
  `X42_…_disjoint_roots.saw` and `X43_…_from_every_sibling.saw`.
- **DF-188k (SPEC/IMPL, filed Aug 9 by unit 7): the prelude gate does not run on
  type ANNOTATIONS.** `func take(d: &Data) -> Int { d.len() }` compiles with no
  `import std.data` — the gate fires in EXPRESSION positions (a call, a struct
  literal, a static-method head), and a parameter annotation is none of those. In
  practice a value of a gated type usually has to be built or called somewhere,
  which is why this has held up; a function that only RECEIVES one and calls
  methods on it never trips the gate. Unit 7 fixed the one position where the
  consequence was an ICE (a `static`'s annotation). The general fix is to run the
  gate wherever a written type name is resolved in user source, which needs care
  about the many internal callers that resolve std-derived types while checking a
  user body — an over-rejection hazard, hence a finding rather than a change.
  **Design 193 unit 7 built it and BACKED IT OUT** — the hazard is real and its
  cause is now known: see DF-193d above (the written spelling is destroyed
  before any check can read it, so a legal qualified annotation is refused).
  **CLOSED Aug 10 by design 194 unit 4**, through the written-form provenance
  bit DF-193d specified. Eleven annotation positions are gated; see DF-193d for
  the mechanism, the exemptions and the consumer sweep.

Also from the audit, for the record: DF-174h's failure mode CHANGED — the
too-deep `??` default no longer emits invalid IR; it silently takes the
absent path (audit row O10). The type error is still owed (187 unit 7,
note updated there). Audit rows confirming fixed items: V17 (DF-146j),
O10/O11 controls, the 26/26 trap table.

## Design 201 — spawn reference parameters (LANDED Aug 10)

`designs/201-spawn-reference-parameters.md` — design 189's unbuilt unit 4,
ratified as its own brief. `group.spawn(f(&var buf))` is legal in a
SINGLE-THREADED group on exactly the extent machinery 189 built for captures:
the argument borrows its ROOT for the task's life, the handle carries the
borrow, `join()` releases it, a discarded handle holds to group death, and the
loop-body liveness refusal applies. An MT group refuses on `Send`. All four
units landed, tracked battery green; design 88's blanket refusal and its pin
`examples/coro_spawn_ref_rejected.saw` are retired, and conformance rows R25 and
K04 are re-authored to the ruling. Two answers the units produced are in the
brief: the declared-after-group question (it does NOT fall out of 188's rule)
and the dual-role trampoline regression the probes caught.

- ~~**DF-201a — the ratified relaxation is not built, and the two holes it must
  close are only invisible because the shape cannot be written.**~~ **CLOSED by
  units 2-3** (Aug 10). The four refusals are the typechecker's (unit 2: the
  extent intake takes a reference ARGUMENT through one funnel beside the
  capture, and design 188's LIFO check reads the same list); the two accepts and
  the MT refusal are the lowering's (unit 3: design 88's blanket refusal
  retired, the spawn site casting `&var x` to a pointer exactly as a drive site
  does, and the Send gate left to refuse the multi-threaded case on its own
  terms). All seven pins flipped. Original text:

  **DF-201a — the ratified relaxation is not built, and the two holes it must
  close are only invisible because the shape cannot be written.** Probed Aug 10
  (unit 1, `.build/scratch/probe201_*.saw`) by lifting design 88's blanket
  refusal and running the shapes the extent model is supposed to cover. Two of
  them are silent use-after-frees in safe code — the SAME two design 189's
  probes found through a capture, reached through an ARGUMENT instead:
  - **declared-after-group (probe H).** A root declared after its group, handle
    discarded: LIFO tears the root down first and the task's pushes print AFTER
    "scope ends", exit 0. This does NOT fall out of design 188's rule — that
    check walks a spawn's capture LISTS and never looks at its arguments — so
    the brief's "verify, row either way" question is answered: it owes an
    implementation, not just a row. Row K18.
  - **`move` of a borrowed root between spawn and join (probe I).**
    `consume(move buf)` compiled, printed `consumed 0`, dropped the buffer, and
    the task then pushed three elements into freed storage. Design 189 probe
    5's shape, one position over. Row K20.
  Two more shapes compile today with no diagnostic: a caller read/write of the
  root inside the spawn-join window (probe B — the caller read `1`, the task
  then wrote through the same root), and one textual spawn in a loop body
  opening N live exclusive borrows (probe E). Rows K15 and K17.
  Cited by the seven XFAILs `examples/conformance/K14`-`K20`; K15/K17/K18/K20
  flip with unit 2, K14/K16/K19 with unit 3.

## Design 189 — scoped task borrows (UNITS 1-3 LANDED, Aug 9; unit 4 NOT built)

`designs/189-scoped-task-borrows.md`, authored from the five-probe
investigation the user directed ("first probe it and then write a brief
depending on the probe outcome"). Probes CONFIRMED TWO SILENT UAFs in
safe code: (a) a deinit-bearing root declared after its group is freed
before the task's write (188's DF-188c(i), now labeled HOLE); (b) `move`
of a captured root between spawn and join hands the task freed memory —
in the ordering 188 calls legal, so extent tracking is REQUIRED for
soundness, not hygiene. Also probed: two `&var` captures of one root
co-live silently (Law violated); MT captures are ALREADY refused via
Send on the closure param (nothing owed there but a regression pin).
The rule: a capture borrows its root for the task's life, the HANDLE
carries the borrow, join releases it (group death is the fallback for a
discarded handle); an exclusive capture excludes caller reads too —
standard XOR over a task-length window. Design-88 param relaxation rides
as an optional unit, ratified separately — **RATIFIED Aug 10, now its
own brief: design 201** (spawn reference parameters on the extent
model; unit 4 here is superseded by it). RATIFIED Aug 9; queue slot:
immediately after 188, before 186. Queue RESUMED same day:
184 ∥ 187 dispatched, then 188 → 189 → 186 serial.

Standing after design 188 landed (Aug 9): (a) is CLOSED — DF-188c(i) is a
compile error naming the LIFO order, and its pin flipped. The `move`-the-group
route (b) depended on is closed too, by DF-188d's `NoMove`.

Units 1-3 LANDED Aug 9 in three commits, full suite green at each. A reference
capture into `group.spawn(...)` now borrows its ROOT for the task's life, the
HANDLE carries the borrow, `join()` releases it, and a discarded or unjoined
handle releases at the group's death. Not a new checker — a new EXTENT: the
records live beside the move state and five existing access sites consult them.
Diagnostics are the existing exclusivity/move errors plus one sentence naming
the task and its release point. All three pins flipped; two error pins and one
accept pin were added for the edges (see the brief). Unit 4 (the design-88
reference-PARAM relaxation) is NOT built and still needs its own ratification —
its precondition, the extent model proved in the capture position, is now met.

- **DF-189a — CLOSED (unit 1).** Two `[&var]` captures of one root co-lived
  silently: both tasks mutated the one root, two exclusive borrows across
  suspensions, no diagnostic. Cause: a capture's borrow ended with the spawning
  call, so nothing was live at the second spawn to collide with. Fixed by the
  extent — and with no new site, because a capture list is already part of a
  call's access set, so the second capture collides with the first task's
  borrow exactly the way two captures in ONE call collide. Pin flipped:
  `examples/spawn_capture_alias.saw`.
- **DF-189b — CLOSED (unit 1).** The caller wrote and read a root while a task
  held `[&var]` of it. Both are refused now: an exclusive capture excludes
  readers as well as writers, which is the ratified one-writer-XOR-many-readers
  table over a task-length window. Pin flipped:
  `examples/spawn_capture_caller_alias.saw`.
- **DF-189c — CLOSED (unit 1), the headline.** `move` of a captured root
  between spawn and join handed the task freed memory: the moved-to value
  dropped, the join then drove the task, which read the dead slot and realloc'd
  from the freed buffer, silently, exit 0 — in the declared-before ordering
  DF-188c rules legal. The move-while-borrowed refusal already existed; what it
  lacked was a visible borrow. Pin flipped:
  `examples/spawn_capture_move_root.saw`.
- **DF-189d (filed and CLOSED in the same landing, unit 1): a capture still
  live when a LOOP BODY ends.** One textual spawn, N live borrows — the Law
  violated by iteration rather than by a second line, and outside the letter of
  the brief's probe record. Refused at the spawn, beside the cross-iteration
  MOVE rule already in `_check_loop_body`. Spawn-and-join-inside-the-body stays
  legal. Pin: `examples/errors/spawn_capture_across_iterations.saw`; accept side
  in `examples/spawn_capture_join_releases.saw`.

## DF-182f — irdet's fan-out lost its accidental throttle (FOUND + FIXED Aug 9, live incident)

Design 182's cooperative `Command.run()` removed a throttle nobody knew
existed: irdet spawned check_one for EVERY corpus file into
`TaskGroup(threads: jobs)` and relied on `run()` BLOCKING its worker
thread to cap children at the worker count. Post-182 `run()` parks, the
workers pick up the next task and launch its child too, and `--all`
put ~1000 concurrent sawc processes on the machine — loadavg >700,
observed live with two agent batteries running. Fixed in
`devtools/irdet/src/main.saw`: the fan-out is now WAVES of at most
`opts.jobs`, joined in input order before the next wave spawns — the
bound the flag always promised, made explicit instead of accidental.
LESSON for every driver of subprocess fleets (the test runner is safe —
it has its own worker pool — but future Saw tools are not): a spawned
task that runs a child process must be bounded by STRUCTURE, not by the
hope that some call blocks. Both in-flight agents were stopped mid-run
for the fix; their worktrees predate it, so their batteries must not run
`--all` until rebased.

## Design 187 — coro fix batch + 182 completion (LANDED, Aug 9)

`designs/187-coro-fix-batch.md`. All eleven units landed, each its own commit
with the full suite green: DF-158e, DF-158c, DF-158a, DF-158b, DF-158d, DF-188e,
DF-174g, DF-174h, DF-182e, DF-182c, and unit 11's cooperative
`Command.output()`. Five pins flipped and were renamed
(`coro_panic_value_position`, `coro_tail_suspend_void`,
`coro_ref_param_compound_assign`, `coro_move_scrutinee_span`,
`process_output_concurrent`); three findings were filed along the way
(DF-187a, still open; DF-187b and DF-187c, both closed).

**Unit 11: `Command.output()` is cooperative, and DF-181a CLOSES WHOLE.** The
drain is a `blocking` extern, so design 183 runs the pipe read on a worker
thread and the task parks — the seam still blocks, just never on the executor
thread. The reap is a shared `Command.reap` METHOD, the same park loop `run()`
has used since design 182. `__saw_rt_proc_wait` drained to zero callers and was
REMOVED from `RUNTIME_ABI_SYMBOLS`, rt/ABI.md and `rt/common/proc.saw`: a seam
with no callers is one a new runtime should not be asked to write.

Three things the first attempt measured, and the landing confirms:
- **`reap` must be a METHOD.** As a std FREE function the transform cannot embed
  it (design 84 embeds std METHODS; the closure walk over free functions is
  entry-module only), so its `io_wait` ran outside a frame, the wait became a
  busy poll, and `process_run_concurrent` / `process_cancel_during_child` both
  regressed. Measured, not reasoned.
- **`output()`'s own buffers had to stop being raw pointers.** A frame holding
  an `UnsafePointer` across the offload park is not `Send`, so `output()` itself
  would have been unspawnable into a multi-threaded group — the very thing unit
  9 unblocked for its callers. The chunk is a frame-resident `[Int8; N]` (design
  183's documented offload idiom) and the accumulator a `Data` (Send since unit
  9, and it grows itself), which deleted the hand-rolled realloc loop and its
  manual NUL terminator from std. Pinned:
  `examples/process_output_multithreaded.saw`.
- **Then irdet stopped compiling** — DF-187b, which is fixed above, and DF-187c
  one layer under it, which the fix then exposed. Both were pre-existing
  transform bugs in shapes irdet happens to be written in.

The brief's "two lines on run()'s park loop" underestimated it: the two callers'
shapes differ enough that the reap has to be shared as a method and the drain
has to give up its raw buffers.

- **DF-187c (COMPILER, CLOSED Aug 9 in unit 11's landing; PRE-EXISTING): a
  `return` inside a control-flow block reached through an EXPRESSION lowered
  raw, emitting invalid IR.** The transform turned a `return` into the frame's
  done sequence only where the construct holding it WAS the statement
  (`_lower_inplace`'s if/while/match branches). Reached through an expression —
  a `match` that is a `let`'s value, a value `if`'s branch, an assignment's RHS
  — only the identifiers inside were rewritten, and the `return` stayed a
  `return` out of a resume method whose result type is `__Poll`: llvmlite
  rejected the module with ``value doesn't match function result type 'i32'``,
  which is the only thing in the pipeline that noticed. `_rewrite_expr` now
  treats a `Block` as a lowering boundary, which covers every expression
  position at once; `ClosureExpr` returns before it, so a closure's own `return`
  is untouched. PIN: `examples/coro_return_in_expression_block.saw`.

## Design 185 — const bitwise + flag enums (LANDED, Aug 8)

Closed items: see todo_aug1-aug9.md.

- **DF-185b — CLOSED (design 186 unit 7).** A `static` initializer was
  literals-only, so a constant EXPRESSION could not initialize one:
  `static SIZE: Int = 4 * 1024` and this brief's own `static RW: UInt8 =
  Perm.Read | Perm.Write` were both refused even though the same
  expressions folded in every position that CONSUMES a constant. Design
  41's `_is_const_init` was a hand-written list kept apart from the
  evaluator; it ASKS the evaluator now (by trying it, not by re-listing
  its grammar), codegen emits the folded value, and a static initializer
  is a const position so the flag-enum half reads its operands as tags.
  All three of the filed ordering questions were answered as the finding
  predicted: `_collect_const_statics` evaluates in DECLARATION ORDER —
  which is also the cycle rule, since a forward reference has nothing to
  fold against — and reads raw-backed enum case values straight off the
  AST, and the answer is decided once, on the symbol, so an importer sees
  what the declaring module decided. Pin flipped and renamed:
  `examples/static_const_expr_init.saw`.

## Design 158 — logical task backtraces (LANDED, Aug 8)

Three units landed: the per-monomorphized-frame state tables as one
read-only in-binary blob (`__saw_bt_table`, always on), `tools/lldb_saw.py`
(`saw tasks` / `saw bt` / `saw table`), and the alloc-free in-process dump
(`dump_tasks()` from std.task, plus the automatic post-panic one) hosted and
freestanding.

**SIZE (the reserved veto point).** 246-517 bytes per hosted program across
the nine-program gate corpus — 0.23% to 0.83% of the binary. 287 bytes for the
SOS kernel image that runs tasks. 138 bytes for a program with NO coroutine
frames at all (header + the debugger's executor descriptor + the string table)
— the SOS kernel that spawns nothing, and Blade, both land there. A frame
record is 24 bytes, a state entry 12, and names are shared in one string
table, so the cost tracks frames rather than program size.
`tools/test_bt_table.py --sizes` reprints it any time. The debugger's vtable
map (unit 2) adds one pointer per frame on top.

Five findings, ALL PRE-EXISTING (each reproduced on `main` before 158
touched anything). Two carry XFAIL pins; three are recorded here because
they have no user-facing spelling to pin.

**DF-158a — CLOSED (design 187 unit 3).** A diverging `panic` in RESULT
position of a suspending body was a codegen ICE: the transform stored the
panic's (nonexistent) value into the frame's `__result` and codegen stored a
Python `None` (`'NoneType' object has no attribute 'type'`). The done
sequence now asks whether the result expression is `Never` — which covers
the tail `panic`, the explicit `return panic(...)`, a `-> Never` callee and
a value `if` whose arm diverges — and emits the expression instead of a
store, exactly as it already did for a `Void` body. Pin flipped and renamed:
`examples/coro_panic_value_position.saw`, now covering all four spellings.

**DF-158b — CLOSED (design 187 unit 4).** A suspending call in a `Void`
body's TAIL position was rejected: the tail normalization turned
`func f() { yield_now() }` into `return yield_now()`, and a suspending call
as a RETURN VALUE is a nested/expression position the state split cannot
express — so the author got a message about a shape they did not write, and
any statement after the call made it compile. A `Void` body HAS no result,
so nothing in it is ever in tail position in that sense: the normalization
now treats a Void body's tail as the discard it is and lowers it exactly as
a statement. That also closes the audit's X23 (a bare `yield_now()` as a
block's final statement read as expression position) and lets
`sos/tests/taskdump.saw` drop the `return` it was carrying as a workaround.
Pin flipped and renamed: `examples/coro_tail_suspend_void.saw`, grown to
cover the bare intrinsic, a nested suspending call, and trailing
`if`/`match` tails.

**DF-158c — CLOSED (design 187 unit 2).** An `@export`ed seam's return WIDTH
was wrong on a 32-bit target: `-> Int64` emitted `define i32` for riscv32 and
`-> Int` emitted `i64`, the two swapped. The cause was the compiler's OWN
declarations, which an `@export` of the same symbol unifies with and inherits
its type from — `_declare_io_runtime` hardcoded i64 for a family of seams
rt/ABI.md calls `word`, and `_declare_seams` used the platform word for the
two clock seams the document calls `Int64`. `--runtime-provider` could not
see it: it compares the SAW-declared types, which were correct all along.
Both directions now read their width off rt/ABI.md's vocabulary. Regression:
`tools/test_ir_contract.py` checks EVERY declared and defined `__saw_rt_*`
against `runtime_abi.abi_signatures()` at 64 and 32 bits — the same parse
`--runtime-provider` uses, so one document governs both sides. The SOS
`taskdump` case is no longer arm64-only.

**DF-158e — CLOSED (design 187 unit 1).** A `-c` / freestanding compile did
not EMBED a nested suspending callee. `object_only` decided `is_entry`, and
`is_entry` gates the whole-program effect fixpoint, so under `-c` every
callee's `suspends` bit stayed False and the closure walk never reached a
spawn root's suspending callees: `fmiddle` got a frame, `fleaf` did not, and
the call lowered as a direct BLOCKING call — in a kernel the nested park ran
inline. The fix SPLITS the flag: `is_entry` now means "the last module of
the compilation unit" (it always was, for an object too) and the new
`require_main` carries the entry-point requirement. `sos/tests/taskdump.saw`
is two frames deep as a result, which is the honest proof. Regression:
`tools/test_ir_contract.py` (`make ircontract`) requires the frame set to be
IDENTICAL with and without `-c` over four coroutine shapes — an examples test
cannot spawn under `-c`, so the check is at the IR level.

**DF-158d — CLOSED (design 187 unit 5), and the culprit is the SPELLING.**
`yield_now()` in a nested callee did not make its caller suspend — the
callee got no frame, the yield ran outside one, and the task never ceded,
silently killing the one documented escape hatch a compute loop in a helper
has. Narrowing it found the bare spellings (`import std.task.*`,
`import std.task.{yield_now}`) were always fine: they put the name in scope
BARE, which lands in the intrinsic branch. Design 150's QUALIFIER spelling
`task.yield_now()` arrived after design 114 and resolved to the std WRAPPER
as an ordinary cross-module free function, which the transform cannot
embed. The wrapper is transparent by design, so the qualified call now
routes to the intrinsic too (marked at resolution, canonicalized to the bare
`FunctionCall` by a transform pre-pass, so every downstream pass sees the
one spelling it already handles). Test:
`examples/coro_nested_yield_wrapper.saw` — the witness COUNTS its own turns
taken while the worker is still running, no ordering asserted; zero before
the fix, nonzero after.

- **DF-187a (COMPILER, FILED Aug 9 by design 187 unit 5; PRE-EXISTING): a
  RENAMED selective import of a std FUNCTION is a codegen ICE.**
  `import std.task.{dump_tasks as dt}` type-checks (the rename registers the
  symbol under `dt`), then codegen looks the call up by the name at the call
  site: `internal compiler error: Undefined function: dt`. The same rename
  over a USER module (`import helper.{greet as hello}`) works, and so does a
  renamed std TYPE (`import std.data.{Data as Bytes}`) — so it is the std
  FUNCTION path, not the rename machinery. Found while narrowing DF-158d,
  whose `{yield_now as cede}` spelling hits it; every std function does.
  PIN: `examples/import_std_function_rename.saw`.
**DF-187b — CLOSED (Aug 9), and the cause was a TUPLE the walk could not see.**
A suspension-spanning `if let` renames its binding to a unique frame field and
rewrites the body's uses; the rename walk descended through lists and
`Argument`s but not through TUPLES, and `StructInit.field_inits` is a list of
`(name, value)` pairs — so it walked straight past every struct literal, the
outer name survived unrenamed, and the re-check reported ``undefined variable
`a` ``. Nothing to do with nesting, tails or interpolation: those shapes all
worked because none of them puts a name inside a tuple-shaped field.

  A dozen walks in `coro_transform.py` hand-rolled that same recursion and the
  copies did not agree, so the fix is ONE `_child_nodes(node)` generator — every
  AST child through any nesting of lists, tuples and `Argument`s — and the five
  walks that were missing tuples now share it. Three of them had the same hole
  in a position that MATTERS and nobody had hit yet: `_iter_method_calls` and
  `_iter_function_calls` (a suspending method call written in a struct-literal
  field would not have been discovered, so no frame, so a silent blocking call)
  and `_reject_buried_suspend_call` (which would not have caught it either).
  Order is unchanged for the shapes that already worked.

  Pin flipped and widened: `examples/coro_nested_iflet_struct_init.saw` — the
  original struct-literal tail, a `MapLiteral` tail (the other tuple-shaped
  field), and nested struct literals two levels deep.

  Original finding follows.

- **DF-187b (COMPILER, filed Aug 9 by design 187 unit 11; PRE-EXISTING): a
  STRUCT INIT in the tail of a nested suspension-spanning `if let` loses the
  OUTER binding's frame rewrite.** Two nested split `if let`s, and a struct
  literal in the inner branch's tail naming the outer binding: the transform
  leaves the name a plain local, and the re-check reports ``undefined variable
  `a` ``. The struct literal is the whole of it — the bare tail `a + b`, the
  bare tail `"{a} vs {b}"`, a struct init one level down, and reading the outer
  binding into a `let` before the literal all work, so it is not the nesting,
  the tail position or interpolation. Reproduces with NO `move` anywhere, so it
  is not DF-182c's surface. PIN:
  `examples/coro_nested_iflet_struct_init.saw`.

  **This is what blocked design 187 unit 11.** `devtools/irdet`'s `check_one` is
  exactly this shape, and a suspending `Command.output()` turns it into a
  coroutine — so the devtool stops compiling, and irdet is a gate. Everything
  else unit 11 needs is built and measured; see the design-187 section above.

## Design 180 — sleep(Duration) (LANDED, Aug 8)

Closed items: see todo_aug1-aug9.md.

**Aug 8 review: all three items below RATIFIED as-is** (the prelude file
move, the negative-span panics, the `as_` renames). The panic ruling is
now a stated API principle: **panic on inputs the caller could have
checked** — a caller bug — and reserve Result/status returns for
conditions the caller could not reasonably know about (allocation
failure, a peer dying mid-operation). It is the same line the accessor
rule draws. Carried into SOS as designs/178 pin 6: an invalid handle
crashes the process.

- **DF-180a (OPEN, filed Aug 8): a static and an instance method cannot share
  a name.** `Duration.secs(2)` (construct) and `d.secs()` (project) are never
  ambiguous at a call site — one names the type, the other a value — but
  declaring both is rejected: ``method `secs` is already defined for struct
  `Duration` with an indistinguishable signature``, hinted "overloads must
  differ in arity or parameter types". The distinguishability check does not
  consider whether a method has a `self` receiver, though resolution reaches
  the two through separate paths. It cost design 180 the accessor names the
  brief asked to keep: the family was renamed `as_nanos` / `as_micros` /
  `as_millis` / `as_secs` so the constructors could be `ns` / `us` / `ms` /
  `secs`. That reads well (bare name constructs, `as_` projects) and is what
  Rust does, so this is not urgent — but the rule as written rejects a
  program with no ambiguity in it, and a receiver-aware key looks small.

## Design 184 — hostname resolution (LANDED, Aug 9)

Brief: `designs/184-hostname-resolution.md`. All four units landed; **DF-181d is
CLOSED WHOLE**. `TcpStream.connect` dials the host it is given, and a NAME is
resolved on a worker thread while siblings run.

Unit 3's resolver half landed on top of DF-184a's fix, and it is three methods
where it was one:

- `connect` chooses. A dotted quad is dialled directly (no libc, no thread hop,
  no way for a literal caller to pay for the resolver's existence); anything
  else is resolved and the first IPv4 answer dialled. A resolution failure, and
  a resolver that succeeds with no IPv4 address, are both an `Err(IoError)`
  naming the host: `io error: resolve "db.internal" failed (not found)`.
- `TcpStream.resolve_first` is a static METHOD, and that is the load-bearing
  part: the transform embeds a suspending std method as a sub-frame and cannot
  reach a std FREE function, so the same code written as a free helper would run
  its `blocking` seam outside a frame — a naked call holding the executor thread
  for the whole lookup, which is exactly what design 184 exists to prevent. It
  is `unsafe` so the pointer work is confined (design 130) and `connect` keeps a
  safe signature. Its `found` buffer is a frame local, satisfying design 183's
  pointer rule.
- `TcpStream.dial` is the shared tail, so a name and a literal reach their peer
  through identical code.

Pins: `examples/net_connect_by_name.saw` (XPASS flipped — the dialer is spawned
FIRST and the sibling still prints first, which is the offload proof) and
`examples/net_connect_unresolvable_host.saw`, rewritten because its old
expectation WAS the refusal. Its unresolvable hosts are now the two the resolver
rejects out of its own input validation — an empty host and a name past the
255-octet limit — so it stays network-free; a name that merely does not exist is
deliberately not tested, since whether and how fast it fails is a property of
the machine's DNS.

**DF-184b — CLOSED, verified on the IR.** With `connect` embedded, its park is
in-frame: at `-O0` the reactor arm sits in `__Frame_TcpStream_dial_resume` with
a real wake token, and the offload start in
`__Frame_TcpStream_resolve_first_resume`. The out-of-frame form (`io_register(…,
0)` + `__saw_exec_park(-1)`) survives only in the untransformed std bodies the
transform leaves behind as dead code, which is how every embedded std method
already looked. A call from a NON-suspending `main` still reaches those bodies
and still blocks that thread — but `main` is not a task, nothing is scheduled
behind it, and that is the general rule for a suspending method called from
non-suspending code rather than anything specific to `connect`.

What landed earlier:

- **The literal fast path** (`parse_ipv4_literal`, std.net). A dotted quad is an
  address, so it is parsed in Saw — no libc, no thread hop — and dialled
  directly. Strict: four octets, 1-3 digits, no leading zero, nothing else in
  the string; a near-miss like `127.00.0.1` answers `None` rather than picking a
  side in the "is a leading zero octal?" ambiguity. Test:
  `examples/net_ipv4_literal_parse.saw`.
- **The seam.** `__saw_rt_resolve_ipv4(host, out, max) -> count | -tag` is in
  the frozen ABI, and its ABI.md entry is the FIRST to state a blocking contract
  explicitly (the 181 audit's documentation standard). Body in Saw
  (rt/common/os_ops.saw): AF_INET/SOCK_STREAM hints as a typed struct pinned by
  `static_assert`, `getaddrinfo`, the walk, `freeaddrinfo`, the EAI mapping.
  Three projections are C in `shim.c` beside `__saw_open_flags`, for the same
  reason: glibc declares `ai_addr` before `ai_canonname` and macOS the other way
  round (a hardcoded offset cannot be right on both — the design-122 `d_name`
  bug, which shipped), and the `EAI_*` codes disagree in value AND sign.
- **The design law is ENFORCED, not just written down.** Because `blocking` is
  part of an extern's contract (design 183 unit 1), a program that redeclares
  `__saw_rt_resolve_ipv4` without the annotation is refused at its own
  declaration: there is no way to spell a naked resolve.
  `examples/errors/resolve_seam_must_be_blocking.saw`.
- **The seam offloads**, proven by INTERLEAVE rather than by stopwatch — one
  cooperative thread, the resolver spawned first, the sibling's line printed
  first anyway (`examples/resolve_seam_offloads.saw`). Network-free throughout:
  `localhost` comes out of /etc/hosts and no test in the suite leaves the
  machine.
- **The address travels the whole way down.** `__saw_rt_tcp_connect_start` takes
  `(addr_be, port)` and `_connect_check` takes `(fd, addr_be, port)` — it must
  re-issue against the same peer or it is asking a different question —
  `loopback_sockaddr` is gone. Pin:
  `examples/net_connect_dials_the_host_it_was_given.saw`, which keeps a live
  listener on 127.0.0.1:port and watches the all-ones broadcast address be
  refused beside it. The old code answered Ok to both.

**DF-184a — CLOSED (Aug 9). A suspending STATIC method is now embedded exactly
as an instance one is.** The transform asked the RECEIVER what type owned a
method callee, and a static call has no receiver; a static call now carries the
owner on the CALL instead (`is_static_method_call` / `static_receiver`, stamped
by both static-call checkers), and one shared `_method_call_owner` answers for
both shapes at the five places that used to read `mc.object.resolved_type`. The
frame itself splits `is_method` (this frame belongs to a type — key, display
name, embedding) from a new `has_recv` (this frame reaches a receiver through a
pointer), and a static frame simply has neither the `__recv` field, the driver's
receiver parameter, nor a `self` to rewrite. `__saw_drive(T.m(...))` follows the
same split. Pin flipped: `examples/coro_static_method_suspends.saw`, both bodies
identical but for the receiver.

  Finding the fix cost one more bug, filed and fixed beside it (below): the pin's
  own INSTANCE half was returning zero, and had been all along.

- **DF-184c (COMPILER, CLOSED Aug 9 in DF-184a's landing; PRE-EXISTING): a
  suspending METHOD call in TAIL position silently discarded its result.**
  `_classify_call` sets `is_ret` in its `return <FunctionCall>` branch and then
  hands a MethodCall to `_classify_method_call` with `is_ret` still False — so a
  tail `recv.m()`, and the design-83-normalized bare tail that becomes one, was
  classified as a bare DISCARD. The callee ran, the caller frame's `__result` was
  never written, and the caller handed back a zeroed value: a spawned task joined
  to 0 (or, for an opt-encoded result, panicked in `TaskHandle.join` on a force
  unwrap of None), a driven one returned 0. At every copy tier, with no
  diagnostic. The `let x = recv.m(); x` spelling was always fine, which is why
  nothing in the corpus caught it. Pin:
  `examples/coro_tail_method_call_result.saw` — the three tail spellings, the
  static twin, and an owning `String` result.

  Original DF-184a finding follows.

- **DF-184a (COMPILER, filed Aug 9): a suspending STATIC extension method
  is unreachable from a task body, and in std it silently loses its offload.**
  The coroutine transform embeds a suspending METHOD callee by its RECEIVER's
  type (`_scan_method_callees` reads `mc.object.resolved_type.struct_name`), and
  a static call has no receiver, so the method is never embedded. Two faces:
  - In the ENTRY module the call does not even resolve. A static method with a
    `yield_now` in it, called from a spawned task, reports ``undefined variable
    `Napper` `` — it names the TYPE as though it were a value. An instance
    method with the identical body works. Pin:
    `examples/coro_static_method_suspends.saw`.
  - In std the call resolves and the body is then compiled UNTRANSFORMED, so
    every suspension in it runs out of frame and a `blocking` extern in it
    lowers to a NAKED direct call — no offload, no diagnostic, the executor
    thread stopped for the duration. Verified on the IR: with the resolve inside
    `TcpStream.connect` the module contains zero `__saw_rt_offload_start` and one
    direct `call @__saw_rt_resolve_ipv4`; moved into `TcpListener.accept` (an
    instance method) the same call offloads. That is why unit 3 stopped: design
    184's whole point is that resolution never blocks the executor, and shipping
    it inside `connect` today would do exactly that, invisibly.

  `TcpStream.connect` is std's only suspending static method, so it is the only
  place this bites in the tree. The fix is coro-transform work (resolve a static
  call's owning struct and build a receiver-less frame) and is left to whoever
  owns that surface. Unit 3's finished contract is written out as an xfail:
  `examples/net_connect_by_name.saw`, interleave included, so the fix validates
  itself. Until then `connect` REFUSES a name — `io error: resolve "example.com"
  (hostname resolution is not available yet — pass an IPv4 address) failed
  (invalid argument)` — which is the honest middle between blocking the executor
  and dialling 127.0.0.1 and calling it success.

- **DF-184b (filed Aug 9, found by 184's investigation): `TcpStream.connect`
  parks OUT OF FRAME, so a slow connect starves every sibling.** Same root cause
  as DF-184a and worth stating on its own because it is live TODAY, with no
  resolution involved: `connect` is not a coroutine frame, so its `io_wait` is
  the outside-frame blocking kind — the one `taskgroup.saw` documents as "a sync
  connect wait" that polls the reactor inline. The scheduler is not pumped and
  no sibling runs while it waits. Loopback hides it (a local connect completes in
  microseconds); a real peer that does not answer does not. The design-181 audit
  did not catch this one because it inventoried EXTERNS, and this is a park.
  DF-184a's fix closes it.

- **Future work (out of scope by the brief, recorded so it is not re-derived):**
  IPv6 and happy-eyeballs, which need the dual-stack design first — the seam is
  named `_ipv4` and returns a `u32` array precisely so a v6 seam is an ADDITION
  rather than a reinterpretation; resolver CACHING (a TTL-aware cache is a
  policy question — whose TTL, whose eviction, and does a long-lived server want
  its own?); and `Command`-env-style HOSTS INJECTION for tests, which is what
  would let a starvation test drive a deliberately slow lookup instead of
  relying on the interleave proof this brief used. A connect TIMEOUT is a
  separate net design over design 180's `Duration`.

## Design 183 — the offload story, made real (LANDED, Aug 8)

DF-181e and DF-181f are both closed above; the offload now works on the seams
and the signatures the design-181 audit needed. Four things worth a look at
review, each a decision the brief left to the implementation.
**The two open ones — the blocking-conflict ERROR and Float in the
offload set — were RATIFIED as-is by the user Aug 10** (error is
relaxable later, the upgrade would not be; Float rides the governing
"whatever @export admits" rule at zero cost). Nothing further owed:

- **A contradicting `blocking` redeclaration is an ERROR, not an upgrade.**
  DF-181f could have been fixed either way. Making the annotation win would give
  a user the whole-program escape hatch of annotating a std seam — and would let
  a downstream declaration turn a function another module calls into a suspension
  source, landing errors inside code its author never wrote. The audit's escape
  hatch does not need it: a user offloads their own distinctly-named wrapper, and
  DF-181e is what makes that wrapper spellable. Relaxing this later is possible;
  the reverse would not be.
- **The thunk is COMPILER-synthesized, so the C shim never casts a function
  pointer.** The alternative was an arity switch in `shim.c` casting `job->fn` to
  `long(*)(long, long, ...)`, which is the usual trick and is undefined behavior
  that happens to work on both integer-register ABIs. Emitting
  `__saw_blk_thunk$<extern>` in IR instead means the real call is made with the
  extern's real LLVM signature by the same lowering every other extern call uses.
  `shim.c` lost a line rather than gaining a switch.
- **Float is in the offloadable set**, because the brief's rule is "whatever
  `@export` admits" and `@export` admits it. It costs nothing: the thunk moves a
  `Float` through the job's integer word as bits, exactly. The brief's
  parenthetical list omitted it; the governing sentence did not.
- **The argument slots are copied into the JOB, not borrowed from the caller.**
  The worker reads them at a time `start` cannot bound, so the alternative was to
  make the call site's slot array outlive the park, which would have put it in
  the coroutine frame and coupled the thunk to frame layout. `start` copies,
  `take` frees after the join. The call site's array is an entry-block slot, so
  an offload inside a driven loop does not grow the resume frame's stack.

## Design 186 — UnsafeMutableInterior (APPROVED + QUEUED, Aug 8)

Brief in `designs/186-unsafe-mutable-interior.md`, fully ratified: interior
mutability as ONE unsafe primitive + a computed cell-carrying property,
replacing the three compiler-known names; `UnsafeSync`/`UnsafeSend` declared
markers (Sync/Send stay derivation-only); Mutex rebuilt inline (futex /
os_unfair_lock, zero = unlocked, static-eligible); `Once<T>` promoted in as
the set-once static (splitting `unsafe static var` back to genuinely-mutated
state); three-tier statics fence (zero / memberwise-const / never-runtime).
Queue position: after the current wave and the net track — typechecker +
codegen + builtin.saw + std surface, shares with everything, runs alone.

## Design 182 — Command without threads (COMPLETED by design 187, Aug 9)

Closed items: see todo_aug1-aug9.md.

**`Command.run()` landed cooperative here (Aug 8) and `Command.output()` joined
it in design 187 unit 11 (Aug 9): neither spends a thread waiting.** The four
findings this section filed against the `output()` half are all closed — DF-182c
and DF-182e in 187 units 10 and 9, the transform gaps under them in 187's unit
11 (DF-187b, DF-187c). The record of why it did not land at the time follows.

### Why `output()` did not land in 182, and the four findings behind it

Making `Command.output()` suspending is a two-line change to the same park loop
`run()` uses. What stops it is its BLAST RADIUS: suspension is colorless, so every
caller becomes a coroutine frame, and four separate limits turn up in real code
that reads a child's output. Three are transform gaps (two fixed here, one pinned);
the fourth is a language question only the user can answer.

- **DF-182c — CLOSED (design 187 unit 10).** An `if let` / `guard let` over a
  `move` SCRUTINEE whose continuation spans a suspension was rejected. The
  ordering was never the problem — the drop-flag clear belongs in both branches
  of the synthesized dispatch, as recorded — the STORE was: the dispatch's value
  path put the unwrapped payload into a frame field with a copy, which a NoCopy
  payload has none of and an ExplicitCopy one would double-drop. The store is a
  MOVE now: the binding owns the payload the unwrap produced and dies at the end
  of the dispatch arm, so the field taking ownership is exactly what it means,
  and an ImplicitCopy payload loses a retain/release pair it never needed. Pin
  flipped and renamed: `examples/coro_move_scrutinee_span.saw`, grown to the
  `guard let` twin, the None path, an ExplicitCopy payload and an ImplicitCopy
  one, and added to the Guard Malloc ownership lane (`tools/gmgate.py`) because
  a surplus release here reads correct natively. A `move` scrutinee of a
  suspension-spanning `match` stays rejected — several bindings and several
  arms, and not what this unit was scoped to.
- **DF-182e — LANDED (design 187 unit 9), as ruled.** An OWNING container is
  `Send` iff its contents are: `Vector`, `Map` and `Set` inherit their type
  ARGUMENTS' answer (the allocator argument included — a policy type carries
  what it carries, and `GlobalAllocator` is empty), and `Data`/`StringBuilder`
  are unconditional by `String`'s argument. Sync follows the same inheritance
  rather than being pinned False: `&var` access to any of them goes through the
  Law of Exclusivity, so sharing one is safe exactly when sharing its contents
  is. Landed where the ruling said — the by-name override list in
  `namespace.py:_send_sync` — and INTERIM by construction: design 186's
  migration sweep replaces the whole list with declared `UnsafeSend`
  conformances. Tests: `examples/taskgroup_send_containers.saw` (each container
  held across a suspend in `TaskGroup(threads: 2)`, plus a
  `Vector<Vector<Int>>`; counts and sums only, ten repeats one outcome) and
  `examples/errors/taskgroup_threads_nonsend_reject.saw`, rewritten so the
  ELEMENT is what refuses it — a `Vector` of closures, closures not being Send.
  Original ruling text follows. Mechanism NOW: additions to the by-name
  override list (`namespace.py:_send_sync`) in the 182-COMPLETION unit below;
  mechanism LATER: design 186's declared `UnsafeSend` conformances replace the
  whole fiat list in its migration unit. **The 182-completion unit** (queued
  BEHIND 158 + 183 — both hold the coro_transform/codegen surface): the
  Send additions, the DF-182c store-becomes-move fix, `output()` goes
  suspending on `run()`'s park loop, and both pins flip
  (`process_output_starvation_xfail`, `coro_move_scrutinee_span_xfail`);
  `__saw_rt_proc_wait` drains to zero callers and is removed per the ABI
  note. Original finding, for the record: no std
  container was `Send`, so a task that held one across a suspension could
  not run in a multi-threaded TaskGroup. `String` is Send by an explicit carve-out
  ("immutable buffer + atomic refcount"); `Vector`, `Map`, `Set`, `Data`,
  `StringBuilder` are all NOT, because Send is derived structurally and
  `UnsafePointer<T>` poisons any struct holding one (`namespace.py:_send_sync`).
  Verified directly: a task holding a `Vector<Int>` across a `yield_now` is
  refused by `TaskGroup(threads: 2)`.

  This is what actually blocks `output()`. `devtools/irdet` runs its compiles in
  `TaskGroup(threads: N)` and holds the first compile's `Data` across the second
  compile; today that is legal because `Command.output()` does not suspend, and a
  cooperative `output()` makes it a compile error. The devtool is not doing
  anything exotic — "fan compiles out across threads and compare the two results"
  is the plain shape — so working around it in irdet would be hiding the finding.

  The narrow fix is a `Data` carve-out beside `String`'s, and the argument is the
  same one: `Data` is a copy-on-write window over an `Arc<DataBuf>`, the refcount
  is atomic, reads go through `&self` on a buffer that is immutable while shared,
  and the only writes are behind `Arc.with_unique`, which hands out `&var` exactly
  when nobody else holds the storage. The broad fix is a way for a std container
  to say its raw-pointer field does not poison it — the same thing the existing
  `Arc`/`Mutex`/`Channel`/`Task`/`SpinLock`/`UnsafeMemory` overrides say by name,
  which would reach `Vector` and the rest too. Either is a soundness decision, so
  it is the user's, not an agent's.

- **NOT EXECUTED HERE: the Linux half.** `rt/host_linux/proc_wait.saw` is written
  against the documented `pidfd_open`/epoll contract and only COMPILE-checked on
  this macOS machine (`--runtime-build --target x86_64-unknown-linux-gnu` and
  `aarch64-...`, and the emitted object references `pidfd_open` as expected); the
  remote test worker is macOS too. CI is the first real execution. One judgement
  call in it worth review: it declares the libc wrapper `pidfd_open` rather than
  going through the variadic `syscall(2)`, which keeps DF-113c's no-variadic-extern
  rule and turns a libc older than glibc 2.36 into a link error naming the file
  instead of a silently wrong argument register.

## Design 181 — blocking-call audit findings (filed Aug 7)

Full inventory + policy menu in `designs/181-blocking-call-audit.md`.
Headline: **169 externs across sawc/std/ + sawc/rt/, NOT ONE annotated
`blocking`.** The design-103 offload machinery works and is unused by std.

- **DF-181a (P0-adjacent, filed Aug 7): `Command.run()` / `Command.output()`
  starve every sibling task for the child's whole lifetime.** **CLOSED WHOLE
  (design 182 + design 187 unit 11, Aug 9):** `run()` parks on the reactor and
  spends no thread (182); `output()` joined it — its stdout drain is an offloaded
  `blocking` seam and its reap is `run()`'s park loop, shared as
  `Command.reap`. Neither holds the executor thread for any part of a child's
  life. Pin: `examples/process_output_concurrent.saw` (renamed from
  `_starvation_xfail` when it flipped). The v1 blocking reap
  `__saw_rt_proc_wait` had no callers left and was removed from the frozen ABI.
  The original finding follows. Both reap via
  the unannotated `__saw_rt_proc_wait` (waitpid) and `output()` first drains
  the child's stdout through the unannotated `__saw_rt_proc_read_stdout`
  (a blocking `read` on a blocking pipe). The cooperative executor thread
  sits inside them, so nothing else runs. DEMONSTRATED, not inferred: with
  task A running `/bin/sleep 2`, a sibling's FIRST tick lands at 2012 ms and
  it then completes 20 cooperative yields in 0 ms — it was runnable the
  entire time. Unbounded (the child may never exit) and reachable from a
  common, documented API. Test:
  `examples/process_run_starvation_xfail.saw`. Fix is a policy call:
  reactor-integrate the stdout pipe (cheap — std.net already has the
  machinery) and annotate the wait, which fits the design-103 whitelist
  exactly — but see DF-181f, which blocked the annotation at the time (closed
  by design 183 unit 1).
- **DF-181b (P0-adjacent by reach, filed Aug 7): every std.file /
  std.directory seam is a naked blocking call.** **DOCUMENTED (design 182 unit 2,
  Aug 8):** the prompt-by-policy contract is now stated where a reader meets it —
  `//!` module docs on std.file and std.directory, and a paragraph in
  LANGUAGE_SPEC beside the never-block invariant. All three say the same thing:
  synchronous by design, prompt on a healthy local disk, unbounded on a network
  mount / FUSE / device node / FIFO, no per-call opt-out, and a `spawn`-ed `Task`
  is where work that cannot afford the stall belongs. The seams themselves are
  unchanged — the recommendation was documentation, not offload.

  **The escape hatch that is still missing (io_uring).** The only way to make
  file IO genuinely non-blocking without a thread hop is a completion-based
  interface: `io_uring` on Linux, which is Linux-only and a project of its own
  (a submission/completion ring is a different seam shape from the readiness
  reactor, so it is an ADDITION to rt/ABI.md rather than a swap of the fs ops).
  POSIX AIO is not an option — it is a thread pool in libc on both hosts.
  Revisit if a Linux-only fast path ever becomes acceptable; until then the
  documented policy above IS the answer. Original finding follows.
  `__saw_rt_fs_open`/`_read`/
  `_write`/`_lseek`/`_opendir`/`readdir`/`closedir`/`_mkdir`/`_rmdir`/
  `_chdir`/`getcwd`/`_unlink`/`_rename`/`access` — no annotation, and unlike
  the reactor/sleep seams NOT ONE comment in the tree acknowledges that they
  block. Bounded-slow on a healthy local disk; genuinely UNBOUNDED on a
  network mount, a FUSE filesystem, or a FIFO (`File.open` on a FIFO blocks
  until a writer arrives). Recommendation in the brief is prompt-by-policy
  + a documented sentence rather than offload (a thread hop per read is the
  wrong default, and freestanding has no threads at all) — but the silence
  is not defensible either way.
- **DF-181c (filed Aug 7): `Channel.recv` from a cooperative task wedges the
  executor forever.** **DOCUMENTED (design 182 unit 3, Aug 8):** `recv`'s
  docstring now states the consequence rather than only naming the engine — never
  from a cooperative task, the thread it stops is the executor's, the sender that
  would unblock it can no longer run, and `receive()` is a drop-in twin. Still
  only documentation: making the call a compile error inside a suspending body
  (the brief's "better" option) is unbuilt. Original finding follows.
  It blocks the calling thread in `pthread_cond_wait`
  with no sender bound. `channel.saw:206` documents which ENGINE it belongs
  to but never states the consequence, and nothing prevents the call. The
  cooperative twin `receive` is a drop-in. Cheap fix: document it loudly;
  better: make `recv` inside a suspending body a compile error.
- **DF-181d (filed Aug 7): `TcpStream.connect` silently IGNORES its `host`
  argument.** **CLOSED WHOLE (design 184, Aug 9):** the seam carries the address
  and `connect` dials the host it is given; a NAME is resolved through
  `getaddrinfo` on a worker thread while siblings run, and an unresolvable one
  is an `Err` naming it. See the design-184 section above. Original finding
  follows.
  `connect(host: String, port: Int)` never reads `host` —
  `net.saw:389-390` calls `__saw_rt_tcp_connect_start(port)`, whose body
  builds a `loopback_sockaddr`. So `connect("example.com", 80)` dials
  127.0.0.1:80 and reports success. Silent wrong-destination: violates both
  "never hide errors" and "APIs do the expected thing". Related: there is NO
  DNS anywhere in sawc/ (no getaddrinfo/gethostbyname/inet_pton), so the
  classic unbounded-resolver hazard is absent TODAY — but resolution will be
  the worst blocking call in the library the day hostnames land, and should
  be designed offloaded or reactor-integrated from the start, never added as
  a naked seam.
- **DF-181e (filed Aug 7): the design-103 offload whitelist `(Int) -> Int`
  is too narrow to express the annotations the audit recommends.**
  **CLOSED (design 183 unit 2, Aug 8).** The offloadable set is now the C-ABI
  set `@export` already admits — fixed-width integers, Int/UInt, Float,
  UnsafePointer, Void/Never returns — with no limit on arity. The runtime's one
  word is a pointer to the call's argument SLOTS, and `fn` is a thunk the
  compiler synthesizes per offloaded extern (`__saw_blk_thunk$<name>`) that reads
  the slots back at their declared types and makes the real call, so the C ABI is
  the compiler's ordinary extern lowering and the runtime knows nothing about
  arity. `__saw_rt_offload_start` gained `(fn, argp, argc)` and copies the slots
  into storage the job owns; `take` frees them after the join.
  The signature gate moved from the coroutine transform's call site to the
  DECLARATION, beside @export's, with @export's message. Tests:
  `examples/offload_multi_arg_pipe_read.saw` (three arguments, a pointer into
  frame storage that the worker writes through),
  `examples/offload_signature_shapes.saw` (narrow ints, zero arguments, a Void
  return, Float), `examples/errors/offload_signature_reject.saw`. The escape
  hatch DF-181b assumes now exists. Original finding follows.
  Of the naked calls, only `__saw_rt_proc_wait(job: Int) -> Int` fits.
  `__saw_rt_proc_read_stdout` (3 args), every `__saw_rt_fs_*` I/O seam
  (3 args) and `__saw_rt_thread_join` (Void return) are all off-whitelist.
  This also removes the escape hatch the DF-181b policy assumes: a user who
  knows they are on a network mount has no way to offload the read. Widening
  it (multi-arg + a real pool) was already future work; this audit is the
  concrete demand for it.
- **DF-181f (COMPILER, filed Aug 7): the `blocking` annotation is SILENTLY
  IGNORED on `__saw_rt_*` runtime seams — so "annotate the seams" does not
  work today.** **CLOSED (design 183 unit 1, Aug 8).** Cause: neither guess in
  the original finding. `_register_extern_function` discards a redeclaration
  whose parameter and return types match an existing one, and it discarded the
  `blocking` flag along with it — nothing `__saw_rt_*`-specific, just that every
  runtime seam std declares IS such a redeclaration. `blocking` is now part of
  the signature the two declarations must agree on, and disagreement is a clean
  error at the annotation. The annotation deliberately does not WIN instead:
  extern symbols are global by name, so letting a downstream declaration upgrade
  one would make a function another module calls a suspension source from a
  distance. Whoever owns the declaration owns the claim. Both branches pinned —
  `examples/offload_seam_first_tick.saw` (the audit's control probe as a test: an
  annotated seam blocks 300 ms and the sibling's first tick lands under 150 ms)
  and `examples/errors/blocking_extern_decl_conflict.saw`. Original finding
  follows. Design 103 promises an offload or "a clean anchored error,
  never a silent miscompile"; on exactly the symbols this audit would
  annotate, neither happens. Demonstrated three ways: an off-whitelist
  `blocking func getpid() -> Int32` errors cleanly (in both `let` and
  statement position), the IDENTICAL shape on
  `blocking func __saw_rt_last_syserror() -> Int` compiles silently, and
  `blocking func __saw_rt_sleep_ms(ms: Int)` (off-whitelist, Void return)
  compiles AND blocks the thread for the full 2 s with no offload and no
  error. Mechanism not pinned down; the transform's
  `_blocking_extern_sym` does `ns.lookup_function(name)` and checks
  `is_blocking`, so the likely cause is either effect inference never
  marking a `__saw_rt_*` call suspending (leaving the body untransformed, so
  `_check_blk_whitelist` never runs) or the lookup resolving to a
  compiler-registered seam symbol instead of the user's declaration. Blocks
  DF-181a and DF-181b remediation — fix this FIRST.

## DECIDED — Aug 7 afternoon round (user, one-by-one review)

Closed items: see todo_aug1-aug9.md.

- **DF-168b DECIDED: defer with trigger** — revisit when compile speed next
  hurts, or before the self-hosted compiler port freezes the pipeline shape.
- **Float64 DECIDED: implement the Float32/Float64 family** (design 173,
  brief authored; queued after 170/171 integrate — typechecker/codegen
  contention). Spec stays wrong only until 173 lands.
- **DF-155a DECIDED: non-breaking knob.** `output()` keeps its meaning;
  explicit stderr capture/discard control + accessor added beside it.
  Small std.process unit, joins the soundness/semantics batch.
- **Rights-table single-source: BACKLOG** on the tracker's own trigger
  (revisit if kinds multiply).

## Design 174 — the T = U? sweep (Aug 7, probe-only investigation)

Closed items: see todo_aug1-aug9.md.

- **DF-174a — FIXED (design 176 unit 7).** Design 24's decidability rule decides
  whether a return-type MISMATCH can be judged in an abstract generic body, and
  rightly defers that to monomorphization; the OPTIONAL wrap was riding the same
  gate and should not have been. It is decidable abstractly: `-> T?` is an
  optional at every instantiation and a non-optional tail is its payload at
  every instantiation, so exactly one wrap is correct for all of them — `T =
  Int?` included, where `Int?` wraps once into `Int??`. The non-decidable branch
  now performs the wrap (and stamps a bare `None` tail) and nothing else, so
  mismatches stay deferred. The `return x` spelling and the generic METHOD path
  never consulted decidability and were always right; the free-function tail was
  the one path that did. Tests: `examples/optional_generic_return_tail.saw`
  (the pin, flipped) and `examples/generic_optional_tail_return.saw` (the shapes
  that share the path — already-optional tail, `None` tail, diverging tail, value
  `if` arms, generic method, and the `T = Int?` instantiation).
  Original finding follows.
- **DF-174a (COMPILER, P0-severity, filed Aug 7 by the 174 sweep): a generic
  function returning `T?` skips the return auto-wrap for a TAIL EXPRESSION and
  emits MALFORMED LLVM IR.** `func wrap<T>(x: T) -> T? { x }` compiles to
  `ret i64 %x` against a `{ i1, i64 }` result type; the LLVM verifier is the
  only thing catching it, and what it is catching is a skipped optional wrap
  that would otherwise be a type-confused read. **NOT Optional-specific** — it
  reproduces at `T = Int` exactly as at `T = Int?`, so it is a generic-return
  bug the sweep happened to walk into. The `return x` spelling of the same
  function is correct, and so is the non-generic `func w(x: Int) -> Int? { x }`;
  it is specifically `-> T?` plus a tail expression. Severity is the highest of
  this batch: a crash today, a soundness hole if the verifier ever stops
  looking. Test: `examples/optional_generic_return_tail.saw`.
- **DF-174g — CLOSED (design 187 unit 7).** A value needing MORE THAN ONE wrap
  into a nested optional slot was mis-lowered: `let a: Optional<Int?> = 5` left
  the outer layer present with a garbage inner, so the first peel worked and the
  second crashed (exit 133); three layers ICEd. Why the earlier one-line
  recursive fit did not take: the `let` path never CALLED the fit. It leant
  instead on a None-literal placeholder retag whose shape test ("payload is i64,
  target is not") reads a genuine `Int?` exactly as it reads a placeholder — so
  the value was rebuilt from its inner TAG alone, payload dropped, before any
  fit could have run. Both halves landed: the retag now asks whether the value
  IS a `None` literal, and the `let` path fits its value to the annotation like
  every other slot does. `_fit_optional_slot` recurses into the slot's payload,
  so a value any number of layers down gets a real `Some` at each. Boundary
  observed, NOT a bug: a struct LITERAL still refuses a two-layer auto-wrap
  (``field `slot` expects type `Int??` but got `Int```) — a clean error, not a
  miscompile. Promoted from the probes: `examples/optional_nested_wrap_depth.saw`.
- **DF-174h — CLOSED (design 187 unit 8).** `a ?? b` whose DEFAULT is one layer
  too deep was accepted. `v.get(9) ?? v.get(0)` on a `Vector<Int?>` — both
  operands `Int??` — is now the clean type error it always owed, naming both
  types. Why it slipped: the compatibility check reads "could the payload flow
  into the DEFAULT", and `Int?` flowing into `Int??` is exactly the auto-wrap
  rule, so depth was the one thing it could not see. A depth comparison runs
  ahead of it and refuses only a default DEEPER than the payload, leaving every
  ordinary one-layer coalesce untouched. (Symptom history, for the record: an
  invalid-IR crash when filed; by the Aug-9 audit a silent absent path; in the
  peeled-twice spelling an `Can't index at [0] in i64` ICE. All three were the
  same accepted mis-type.) Tests:
  `examples/errors/optional_coalesce_default_too_deep.saw` and
  `examples/optional_coalesce_peel_depth.saw` (the accept side).

## DECIDED — Aug 8 morning round (user, the 181 policy)

Closed items: see todo_aug1-aug9.md.

- **RULED and BUILT:** the DF-181d connect fix scope (IPv4-literals-now vs full
  resolution) became design 184, which shipped both — a literal is parsed in Saw
  and dialled directly, a name is resolved through an offloaded seam.

## DECIDED — Aug 7 evening round (user)

Closed items: see todo_aug1-aug9.md.

- **DF-176a: SKIPPED by choice (user)** — stays filed; the compound
  spelling (`*=`) is the idiom; the RHS-first-vs-clean-error ruling waits
  for a real collision.

## Design 172 note (branch PARKED for user review; full findings ride the branch)

- **PART 2 IS DONE (Aug 7).** Unit 2 landed as written — DF-172e was the only
  blocker and design 177 removed it — and it grew by one symmetric half: the
  seam family's PROCESS end was C for the same reason, so both user
  `syscall.c` files are now their syscall instruction and nothing else, which
  is what their own headers said they should be. The SOS C floor is 383 -> 207
  -> **135** code lines (-65% overall), and every surviving line is an
  instruction or `mem*`/atomics. Three compiler bugs found on the way
  (DF-172f/g/h) are FIXED in isolated commits for cherry-pick to main; DF-172i
  is a coverage note. Full findings below; the branch parks for review.

- **DF-172e CLOSED — "172 part 2" IS DISPATCHABLE.** The decided while{}-Never
  item (decision 9, tracker commit 3134cf7) landed as **design 177**, so
  `__saw_rt_panic`'s frozen `noreturn` signature has a Saw body available: a
  conditionless `while { }` with no `break` types `Never`, and the freestanding
  shape is pinned by `examples/while_never_freestanding.saw`. 172's unit 2
  (arena → Saw, completing the seam family) stopped on nothing else — everything
  around it was probed and measured on the parked branch — so it resumes as
  written. The compiler half of 172 (unit 7, NEON-off default for freestanding
  aarch64) is cherry-picked to main (e6b5cbe); DF-162a CLOSED measured (arm64
  kernel object: 5 NEON block-moves → 0).

- **DF-172j FIXED (RULED Aug 8, landed on main Aug 8).** A module `static` may
  be an array length, a repeat count, a const generic argument and a
  `static_assert` operand. **The entry itself rides the parked 172p2 branch —
  this is the note that reconciles at its merge; do not edit the parked copy,
  mark it FIXED against these commits.** The rule as built: an `Int`/`UInt`
  static whose initializer is a plain integer literal (optionally negated)
  folds, const arithmetic composes over it (`[0; REGION_SIZE * 2]`), and the
  name resolves as an ordinary read does — a local wins (so design 100's derived
  shadow stays the runtime value it looks like), a const generic parameter wins
  over both, and cross-module is the ordinary visibility gate. That closes the
  SOS finding's own case: `static REGION_SIZE: Int = 65536` is now the one
  checked source for `[UInt8; REGION_SIZE]` and `[0; REGION_SIZE]`, and the
  named-array-type-plus-`sizeof` workaround is retired.

  What stays an error, with a message that now says WHICH static and why rather
  than reading as "no static may be named here": a mutable `unsafe static var`,
  a static of any other type, one declared with no initializer, and one whose
  initializer is not an integer literal. DF-172f's pin
  (`examples/array_length_nonconst_error.saw`) was split — its case is legal
  now, so it holds the mutable-static half and `const_static_length.saw` holds
  the legal one.

  CROSS-MODULE, both halves: the BARE spelling works and is pinned
  (`import dep.{REGION_SIZE}` then `[UInt8; REGION_SIZE]`; a dependency's
  PRIVATE static is not nameable at all, so the gate needed nothing new). The
  **QUALIFIER spelling is filed, not guessed — DF-172l below.**

  Implementation shape worth knowing before touching it: `const_eval` stays a
  pure function of the AST (the typechecker stamps the value on the identifier
  node, exactly as it stamps `Int.max` and a raw-enum case on a MemberAccess),
  and the fold reaches DECLARED types through two whole-program walks — lengths
  before registration, const type ARGUMENTS after it, because the second needs
  the referenced type's parameter list. A struct FIELD's type is the position
  that forces this: it is stored as written and is never resolved before codegen
  reads it.

- **DF-172k FIXED (found by the 172j work, landed with it).** Two adjacent holes
  in the same rule, neither about statics:
  1. A NEGATIVE array length. `[UInt8; -1]` and `[UInt8; 2 - 3]` folded and
     reached llvmlite as `[-1 x i8]`, which came back as
     `internal compiler error: LLVM IR parsing error`. The repeat count has
     checked this since design 148; the type position had not. Reported where it
     folds now, and the length is left unfolded so it is one error rather than a
     cascade against `[UInt8; -1]`.
  2. A BINDING's annotation is the one `[T; N]` position codegen never sees:
     when the initializer supplies its own type the annotation is only compared
     against it, and an unfolded length compares equal to anything. `var buf:
     [UInt8; NOPE] = [0; 4]` compiled clean with the annotation silently
     dropped. Under 172j that would have read as the fold WORKING when it was
     the check missing, which is why it could not be left.

  **NUMBERING — reconcile at 172p2's merge.** `k` was assigned here, on main,
  while design 172's own letters ride the parked branch and cannot be read. If
  the parked branch already spends `DF-172k`, renumber THIS one (five citations:
  `sawc/codegen/types.py`, `sawc/typechecker/types.py`, and the two
  `examples/array_length_*_error.saw` headers, plus the landing commit), not
  theirs.

- **DF-172l CLOSED by design 185 (units 2 + 3, Aug 8).** Filed as: `[UInt8;
  dep.REGION_SIZE]` is a **parse error** ("Expected `]` after array type") while
  the repeat count beside it reaches a clean semantic error — one rule, two
  spellings, two failure modes. Both halves are done. Unit 2 gave the type
  position the SAME expression grammar the repeat count takes (`]` closes it, so
  the `>`-delimiter argument that shaped design 148's small grammar never
  applied there); unit 3 answered the resolution question the finding said was
  not to be guessed at, by widening DF-172j's stamping walk from identifiers to
  the member accesses a constant may name — `Int.max`, a raw-backed enum case,
  and a module static, each in both the bare and the qualified spelling, all
  resolved by the ORDINARY machinery (`_module_qualifier` + `get_enum_info`), so
  a local still wins and a private static of another module is still invisible.
  Pinned by `examples/const_qualified_length.saw`, renamed qualifier included.
  The generic-ARGUMENT position deliberately keeps the narrow grammar: there `>`
  really is the delimiter.

## Design 176 findings (places/optional plumbing batch, Aug 7)

Closed items: see todo_aug1-aug9.md.

- **DF-176a (COMPILER, filed Aug 7 by unit 13's probing; PRE-EXISTING, verified
  against unmodified `main`): a place READ in the RHS of a place WRITE to the
  same root is a wrong error or an ICE.** `v[0] = v[0] * 4` on a local root
  reports ``cannot copy value of type `Vector<Int, GlobalAllocator>` which
  implements ExplicitCopy`` — the element is a trivial `Int` and nothing is
  being copied; the same shape through a receiver field
  (`self.cells[i] = self.cells[i] * by`, in a `&self` OR a `&var self` method)
  dies with `internal compiler error: 'self' not found in current scope`. The
  root is `place_uses._assignment`, which lowers the RHS first and then wraps
  the whole assignment in the TARGET's window, so the RHS window ends up NESTED
  inside the write window and two overlapping borrows of one root reach the
  checker with no diagnostic that names them. The compound spelling
  (`v[0] *= 4`, `self.cells[i] *= by`) works and is the idiom, so the
  user-visible cost is a read-modify-write spelling that fails confusingly
  rather than a capability gap. Needs a decision before a fix: either evaluate
  a place write's RHS BEFORE opening the target window (making the shape legal,
  which is what every other language does here) or make it a clean exclusivity
  error naming the two windows and pointing at `*=`. Probes:
  `.build/scratch/p176_scale{,2,4,5}.saw`.
- **DF-176c (COMPILER, soundness, filed Aug 8 by DF-176b's migration sweep;
  PRE-EXISTING): the same lost mutation through a PLACE WINDOW rather than a
  method call.** `self.grid[0] += 100` in a plain `&self` method, where `grid`
  is an inline field of a type with a `borrows` accessor, is a SILENT NO-OP
  (`.build/scratch/p176b_placewrite.saw` prints `first 1`, not `101`); the same
  write in a `&self` BORROWS body LANDS on a `let` root
  (`p176b_placewrite2.saw` — two pure reads of a `let` leave its counter at 2).
  Exactly DF-175a's two consequences, reached through the fourth spelling.
  DF-176b's rule does not cover it and deliberately does not try: the window
  call is SYNTHESIZED by `place_uses._window_call` (marked `place_lowered`), so
  judging it by the `&var self`-method rule would name a method the source never
  mentions — and would reject `lend self.inner[i]`, design 175's legitimate
  forwarding case, which is sound precisely because a borrows body's receiver
  travels by pointer. Wants its own ruling, and it is a real one: the plain-body
  half is unambiguously the vanishing-write bug, but the borrows-body half
  interacts with `#lend_var` (an exclusive specialization may legitimately want
  a place write in its prologue) and with the composition pessimization design
  175 already documented. Fix site is the place lowering, not
  `_reject_var_self_call_on_shared_self`.
  **RE-EXAMINED against design 188 unit 2 (Aug 9) and NARROWED, not closed.**
  Re-probed on the landing: `self.grid[0] += 100` in a plain `&self` method
  still prints `first 1` (`.build/scratch/p176c.saw`). Unit 2 folded place
  window ROOTS into the Law of Exclusivity, which is about how many accesses one
  CALL makes; 176c is about how the receiver reached the window in the first
  place, and a single write through a single window makes exactly one access. So
  the two do not overlap and unit 2 changes nothing here. What the landing does
  settle is the family framing in this entry: the "same lost mutation" cases
  where TWO accesses were involved are now exclusivity errors on every tier, and
  what remains under 176c is exactly the receiver-COPY half — a `&self` method
  writing through a place window on an INLINE field (vanishes), and the borrows
  body writing one on a `let` root (lands).
  **RULED Aug 10, owned by design 200:** the plain-body half is the
  design-176 receiver-write ERROR extended to the synthesized window
  call (fix in the place lowering, exclusive windows only, heap-reaching
  fields keep the carve-out); the borrows-body half is RATIFIED as
  intended behavior (by-pointer receiver; `#lend_var` gates the shared
  specialization).
  **CLOSED by design 200 (Aug 10).** Both probe shapes reproduced exactly as
  filed before the fix — the plain body printed `first 1`, and the borrows body
  left a `let` root's counter at 2 after two pure reads — and each is a
  conformance row now (M31 row 1, M33). The refusal needed a fact the compiler
  did not have: WHERE an accessor lends from. `place_transform` records each
  lending path's shape (`(('member', 'cells'), ('index',))` for
  `lend self.cells[i]`; nothing for a lend through an indirection the receiver
  points at), and `place_uses` walks it against the receiver's real type, so
  design 176's inline-vs-indirect walk gains the one hop it could not take and
  composes through nesting. `lend self.inner[i]` keeps working: the forwarding
  accessor records an `index` hop into a `Vector`, which is not inline, so the
  outer accessor lends nothing inline either. PINS: `examples/conformance/`
  M31 (the seven-row position matrix), M32, M33, M34, M35.

## Design 175 findings (`#lend_var` investigation, Aug 7 — PROBE-ONLY, no compiler changes)

Closed items: see todo_aug1-aug9.md.

- **DF-175c — OPEN (minor, docs). `--emit-docs` cannot distinguish a
  `&var self` borrows accessor from a plain `&var self` method** — the former
  reports `"self": "borrows-var"`, same as the latter, so window-ness is only
  recoverable from the signature string (`docs_emit.py:425-442`). A `&self`
  borrows receiver correctly reports `"self": "window"`. Cheap fix
  (`"window-var"`); matters more once accessors are flavored.

## Design 179 findings (`#lend_var`, Aug 7 — IMPLEMENTED, six units)

Closed items: see todo_aug1-aug9.md.

- **DF-175c stays OPEN** (`--emit-docs` cannot tell a `&var self` borrows
  accessor from a plain `&var self` method). The synthesized twin needed no
  suppression work — its reserved `__` name already falls under `docs_emit`'s
  synthetic-declaration filter — so the flavor note was not the trivial change
  the brief made it conditional on, and 175c is left as filed.

## Design 169 part 2 — std.cbor itself (LANDED, Aug 7)

Closed items: see todo_aug1-aug9.md.

All six units are built; the landing report is at the bottom of
`designs/169-serialize-cbor.md`. `sawc/std/cbor.saw` is the deterministic-profile
codec (import-required, both profiles): `CborDecoder.open` validates the whole
input against max_depth/max_size/max_items over an EXPLICIT work stack before
any typed read runs, so depth is the stack's height and no input reaches the
call stack — a 100000-deep blob is refused at byte 64. Nothing panics on input:
UTF-8 is validated in place rather than through a `String`, and the decoder's one
allocation is the work stack, sized at open. `examples/cbor169_vectors.saw`
WALKS `tests/cbor_vectors/`, so the 32 accept + 20 reject blobs now gate the Saw
codec and `tools/sawcbor.py` together, forever, with no regeneration step; the
`struct_endpoint` and `lock_entry` vectors are reproduced byte for byte by the
`@synthesize` derivation. Unit 6 moved `blade/src/lock.saw` from five parallel
`Vector<String>` to `LockEntry` + `Vector<LockEntry>` with both directions
derived (bootstrap 21 tests to 22, green stage1 + stage2) — but LEFT `Saw.lock`
as TOML on disk, which is the one scope call wanting user ratification (a lock
file is read in review and three are tracked here; the switch is two call sites
if binary was the intent). Findings DF-169e/f/g/h below. The state-of-the-world
the dispatch inherited follows.

## Design 169 — DF-findings (Serialize/Deserialize + std.cbor, units 1/2/5 LANDED)

Closed items: see todo_aug1-aug9.md.

- **DF-169e — a STATIC trait requirement is not callable on a type PARAMETER.**
  Inside `func decode<T: Deserialize>(bytes: Data) -> Result<T, DecodeError>`,
  the call `T.deserialize(from: &var dec)` is ``undefined variable `T` `` plus a
  follow-on "body has no value". The INSTANCE half of a bound dispatches fine
  (`v.label()` under `<T: Named>` works), so this is specifically the static
  call. It matters more than it looks: unit 1 made `deserialize` static so that
  `Deserialize` would be a generic BOUND and never an existential (DF-169b), and
  a bound whose requirement cannot be called generically buys nothing. `std.cbor`
  therefore ships `encode<T: Serialize>(value:)` and NO `decode<T>` twin — a
  caller names the concrete type, `LockEntry.deserialize(from: &var dec)`. Repro:
  `.build/scratch/probe_static_bound.saw` (a two-requirement trait, one static
  one instance, called both ways).
- **DF-169f — a place WRITE whose RHS names `self` is an ICE.**
  `self.marks[0] = self.tick` and `self.marks[0] = self.width()` both die with
  `internal compiler error: 'self' not found in current scope`, no source anchor.
  Place lowering rewrites the write into an accessor call taking the window as a
  CLOSURE and hoists the RHS into that closure body, which never captured `self`
  — so the failure is not about the place at all, it is about what the RHS
  mentions. A literal or local RHS (`self.marks[0] = 4`) is fine, and so is a
  place READ off `self` in any position. Reading the RHS into a local first
  compiles and runs, which is what `sawc/std/cbor.saw` does at its two map-key
  bookkeeping sites (`item_done`, `close_item`). An ICE with no anchor is the
  worst shape a rejection can take, so this is the first thing to fix in the
  places batch. Pinned: `examples/place_write_self_rhs.saw`.
- **DF-169g — the automatic ImplicitCopy tier does not satisfy a `Copy` BOUND.**
  Design 159 put a struct whose owning members are all trivial/ImplicitCopy on
  the ImplicitCopy tier with no declaration owed, and the BINDING half works:
  `struct Ticket { code: String }` compiles bare and `let b = a` is a free retain
  leaving both live. The CONFORMANCE half never registered, so the same type
  fails a `T: Copy` bound — ``type `Vector<Ticket, GlobalAllocator>` has no
  method `iter`: requires `T: Copy`, and `Ticket` does not conform``. std's own
  `Path` is one of these (`struct Path { value: String }`), so `Directory.list`
  hands back a `Vector<Path>` that cannot be iterated; the design-169 vector
  harness reaches each entry as a PLACE instead (`entries[i].ext()`, a borrow, so
  the tier never comes up). The two halves of one tier should agree. Repro:
  `.build/scratch/probe_auto_tier_bound.saw`.
- **DF-169h — a place window refuses a `&var` argument naming a NoCopy LOCAL.**
  `v[i].serialize(to: &var enc)` over an encoder you just built is ``cannot copy
  value of type `CborEncoder` which implements NoCopy``, anchored at the
  SUBSCRIPT, with a `move` hint that would be wrong — the program copies no
  encoder anywhere. Same lowering as DF-169f from the other side: the window
  becomes a closure and the local is captured by value instead of having its
  address taken. Forwarding a `&var` PARAMETER into the same window works, which
  is exactly why design 169 unit 2's derived `Vector` walk never hit it (its
  encoder arrives as a parameter) and why this surfaced only in `blade/src/
  lock.saw`, whose `to_cbor` builds the encoder locally. The spelling that
  compiles is a value read first (`let entry = lock.entries[i]`), which for a
  five-String record is five retains rather than a borrow. Two of the four
  findings in this brief are one bug in the place lowering seen from two sides;
  fixing the capture would close both. Pinned:
  `examples/place_nocopy_arg_in_window.saw`.
- **DF-169i — a std-module static as a DEFAULT PARAMETER VALUE breaks at the
  caller, with a bogus anchor.** `public func open(bytes: Data, max_depth: Int =
  DEFAULT_MAX_DEPTH)` in `sawc/std/cbor.saw` compiles, and so does a call from
  inside std; a call from a user module is ``undefined variable
  `DEFAULT_MAX_DEPTH` `` anchored at an unrelated line of the CALLER (the
  default is substituted at the call site, where std statics are not visible —
  the known cross-module static gap, design 82). Two things are wrong
  independently: the visibility gap itself, and a diagnostic that points at
  whatever line the substitution landed on rather than at the parameter that
  supplied it. `std.cbor` writes its three limit defaults as literals because of
  this, with the names in a comment above them.

## Design 170 — checked integer casts (LANDED, Aug 7)

Closed items: see todo_aug1-aug9.md.

`as` between integer types traps on an unrepresentable value; `T.from(x)` is
the `None`-returning twin and `T.from(truncating: x)` the deliberate wrap.
Follow-ups and findings the sweep produced:

- **DF-170b (FOLLOW-UP, mechanical): re-run the cast census over
  `sawc/std/data.saw`.** Skipped in this sweep because design 165 was
  rewriting the file concurrently. As it stood at 170's dispatch it had 23
  ` as ` tokens, 13 of them pointer casts and ZERO integer casts, so it was a
  no-op for this design — but the rewrite could introduce integer casts, and
  nothing checked the rewritten file. Grep it for ` as ` and triage each hit
  provably-in-range (keep `as`) vs deliberate-wrap (`from(truncating:)`).
- **The `fd as Int32` cluster (~30 sites, KEPT as `as` deliberately).**
  `sawc/rt/common/os_ops.saw` plus both `reactor.saw` files hold fds in `Int`
  fields and narrow at each libc call. Every one is guarded non-negative at
  creation and an fd is always small, so the checked cast now ENFORCES an
  invariant that was previously only true — which is the outcome the design
  wants, not a site to respell. The tidier end state is typing the seam
  fields `Int32` end-to-end so no cast exists at all; that is a refactor
  worth doing on its own, not under a semantics change.

## Review sweep (Aug 4) — TRIAGED (user, Aug 4 evening), briefs 122-127

Closed items: see todo_aug1-aug9.md.

- **DF-146k — OPEN, needs a user decision (Aug 6). A `borrows` accessor cannot
  be declared SHARED-ONLY, so a container whose own invariants depend on an
  element cannot publish one at all.** This is why DF-146d's Set half did not
  land. Design 141 decision 3 puts the window's flavor at the USE SITE, out of
  one declaration — which is right for a Vector element and for a Map VALUE, and
  wrong for a Map KEY or a Set element: `s.get(x)!.mutate()` would change an
  element's hash and lose it in its own table, with no diagnostic anywhere.
  Rust draws the same line by having `HashSet::get` and no `get_mut`; Saw has no
  spelling for it. Options: a `shared borrows` declaration that pins the flavor;
  or accept that slot-keyed containers publish only by-value reads. (The second
  option once floated here, `borrows -> &T`, is gone: a return type that names a
  reference is a parse error since DF-163a's fix.) Until then `Set` has no
  element accessor, and the spec says so.
  **PROBE VERDICT (design 179 unit 5, probe-only — no accessor built). The
  IMPLEMENTATION question is now answered; the DECISION is untouched.** A
  shared-only accessor is expressible TODAY with no new language surface, by
  gating a compile-time reject on `#lend_var`:
  ```saw
  public func [](&self, i: Int) borrows -> Int {
      if i < 0 || i >= 4 { panic("Keys.[]: index out of range") }
      if #lend_var {
          static_assert(false, "Keys.[] lends a KEY: writing one changes its hash")
      }
      lend self.items[i]
  }
  ```
  Reads compile and run; an exclusive use site is a COMPILE ERROR carrying the
  author's own message, verified for both shapes that open one — an assignment
  (`k[0] = 99`) and a `&var` argument (`bump(&var k[0])`). It works because
  `static_assert`'s condition is type-checked at check time but its VALUE is
  evaluated at codegen (`typechecker/statements.py:901-905`), and design 179's
  exclusive twin is a generic method only monomorphized when a use site
  retargets to it: no exclusive use site, no twin emitted, no assertion
  evaluated. The shared copy never contains the assert at all, because the fold
  PRUNES rather than skips.
  NOT SHIPPABLE AS THE SPELLING, for one reason: the diagnostic has NO source
  location — not the write site, not the accessor —
  `error: static assertion failed: Keys.[] lends a KEY: ...` and nothing else.
  For a std `Set` accessor a user would see that and nothing pointing into
  their own code.
  RECOMMENDATION: a viable IMPLEMENTATION, not a viable SPELLING. If `Set`
  should publish a shared-only element accessor, the honest surface is the
  `shared borrows` declaration floated above, LOWERED to exactly this — emit no
  twin, and error in `place_uses._flavored_method`, where the use site's own
  line and column are already in hand (every other diagnostic in that pass uses
  them). Roughly ten lines for a message anchored at the write. Probes:
  `.build/scratch/p179_setlock_{read,write,ref}.saw`.
  Adjacent, same brief: a borrows body cannot FORWARD another conditional place
  (`lend self.map.get_key(k)!` — `lend` takes an
  Identifier/MemberAccess/ArrayIndex/TupleIndex/deref, and even if it took a
  place call, `_span_call` would lower the absent path to a PANIC rather than to
  the caller's `__absent()`). That is what a Set accessor would have needed to
  delegate to Map, and it is the reason a wrapper type cannot re-export a
  conditional place today.

- **DF-146p — OPEN, diagnostic quality (Aug 6; RENUMBERED from DF-146l by
  design 176 unit 12 — see the collision note at the head of the design-176
  findings). An exclusivity violation INSIDE
  a place window is reported as a copy error against the container.** Writing
  `m["a"]!.n += grow(&var m)` (or the Vector form `v[0].n += grow(&var v)`) is
  correctly REJECTED — the window body captures the root the window is holding —
  but the message is `cannot copy value of type Map<...> which implements NoCopy`
  with the hint `use `move` to transfer ownership instead`, which is advice that
  cannot help. The window-closure lowering should attribute a capture of the
  window's own root to the open window instead. Pre-existing (the Vector shape
  behaves identically on main), low severity, wrong-signpost rather than
  unsound.

**Follow-up filed by design 127:** the compute budget cannot reach a loop the
coroutine transform cannot state-split. `_split_for` rejects a suspension inside
a `for` over a NON-RANGE iterable ("use a `while` loop"), so 127 skips such a
loop and everything nested inside it — instrumenting one would turn working
programs into compile errors. A long `for x in v.iter()` in a task body
therefore still starves siblings. Lifting it means teaching `_split_for` to
state-split an arbitrary iterator (hold the iterator in the frame and split
around `next()`), which also retires the existing rejection. Same shape, lower
value: a compute loop inside a SYNC callee is likewise unreachable — that one
wants the instrumentation to follow sync call edges out of a task body, which
would make sync helpers suspending and needs a design decision first. [127]

**Follow-up filed by design 130 (now OPEN — 130 landed Aug 5):** decompose the
oversized functions the unsafe migration marked wholly-unsafe —
`__saw_exec_worker` (~150 lines), the `rt/host_*/reactor.saw` bodies,
`rt/common/os_ops.saw` (15 of the runtime's 47 marks on its own) — so the "an
unsafe function is short enough to review as a unit" policy is actually true.
Shape: extract the raw-pointer bookkeeping into small `unsafe` helpers and leave
the surrounding loop safe. Deliberately NOT in 130 (mechanical migration kept
separate from judgment-heavy refactoring of the executor's hot paths). [130]

**P4 — design/gap briefs to consider:** ~~structural `Deinit`/`ExplicitCopy`
synthesis~~ DONE (design 128: deinit is implicit, copy/equality derivations are
`@synthesize`-gated); ~~DF-121a newline-in-brackets~~ (LANDED as design 129,
Aug 5 — the 210-char `blade/src/resolver.saw` signature that was the evidence
is now wrapped); std gaps ranked G1 bit intrinsics (S–M), G2
checked/saturating arithmetic (S, tracker already wants it), G3 slices
(L, language-level), G4 radix/hex formatting (S), G5 iterator adaptors (M);
compiler pre-port restructures R1 declared AST contract + R2 stable NodeId +
R11 astdiff oracle as the port-order prerequisites (then AST+parser next,
coro_transform last).

## Design 155 — irdet in Saw, the first devtool port (LANDED, Aug 7)

Closed items: see todo_aug1-aug9.md.

### What the port found (the DF product)

- **DF-155a — a child's stderr can be merged, but not captured or discarded.**
  `Command.merge_stderr()` landed with unit 1 because the port could not produce
  readable output without it (a corpus sweep expects ~40 compiles to fail, and
  their diagnostics are not the tool's to print). The fuller question is open and
  is a design decision, not an implementation one: a `CommandOutput.stderr` of
  its own needs a second pipe and a second read seam, and would change what
  `output()` does today for every existing caller. Three shapes are defensible
  (separate capture / discard-to-null / the merge that landed); the user picks.
- **DF-155b — std cannot report the core count.** Python's irdet defaulted `-j`
  to `min(10, cores - 2)`; the port has a fixed 8 with `-j` to override. Wanted:
  something like `System.cpu_count()`. Small, and every parallel tool will want
  it.
- **DF-155c — a `String` cannot be a `static`.** Statics take compile-time
  constants and a String owns a heap buffer, so every named string constant in
  the port is a zero-argument function (`func sawc_path() -> String { ... }`).
  It reads acceptably and the call folds, but the ceremony is visible, and the
  no-magic-numbers ruling pushes toward naming MORE constants, not fewer.
- **DF-155f — verdicts do not stream out during a `--all` sweep.** The tool
  spawns every task, then joins in input order — which is what keeps the report,
  the JSONL stream and the exit status independent of completion order (the
  Python one got that from `executor.map`). But a suspending `main`'s loop is
  charged by design 127, so the spawn loop force-yields and the corpus is largely
  CHECKED before the join loop begins: the JSONL records then land in a burst
  near the end instead of continuously. Every verdict still arrives and the
  worker's heartbeat is independent, so this costs a live progress view rather
  than a result. The fix is a sliding window (spawn `2*jobs` ahead, join the
  oldest), which needs a FIFO `Vector` cannot give — there is no `pop_front`, and
  handles are move-only.

## Design 168 — the compile-speed batch: LANDED (Aug 7)

Closed items: see todo_aug1-aug9.md.

- **DF-168a — `_CatchError_{node_id}` is the last node-id-derived name in the
  compiler.** `typechecker/expressions.py:9077`, the union enum a multi-type
  `try`/`catch` synthesizes. Same class as DF-164a, and its own comment claims
  the name "reaches codegen and the emitted type table" — but no current program
  shows it doing so: `try_catch_multi_match` emits ZERO occurrences of
  `_CatchError_` in its `.ll`, and no `try_catch_*` example is among the 45
  `reemitdiff` flagged. Left alone rather than changed on a guess. The fix is
  NOT the mechanical one the other six got: a `try`/`catch` inside a generic body
  can be checked per instantiation with DIFFERENT error sets, so a position-only
  name would let two unions share one layout. Name it from the position PLUS the
  variant identities, or leave it.
- **DF-168b — the place-lowering re-entry re-checks std for every program, and a
  dirty flag cannot avoid it.** DF-164d, measured after the rest of the batch:
  the re-entry is now the single largest stage of a compile (30.3% of `hello`;
  two passes, ~0.4 s, for a driven program). The obvious saving does not apply —
  `hello.saw` is four lines with no place uses of its own and STILL forces it,
  because the program `transform_place_uses` rewrites is **std** (85 extensions),
  and it `uncheck`s every program in its list once any one changed. std is dirty
  for essentially every program. What WOULD work: std's post-lowering state is
  the same for every program, so cache the pair AFTER place lowering. The blocker
  is that `transform_place_uses` gets ONE merged namespace with no per-module
  scoping, so a user `borrows` extension on a std type could in principle change
  how std's own bodies lower — either a design-142 scoping violation to fix
  first, or a contribution the key must cover. A design question, not an
  implementation detail. Worth its own brief: it is ~30% of every compile and
  design 168's cache machinery is most of the implementation.

## Design 138 — the all-sources docs consistency sweep (LANDED, Aug 6)

Closed items: see todo_aug1-aug9.md.

### DF-138c — CLOSED (design 188 unit 7): `std.slab` is gated

Resolved the second way it was filed: the gate had a hole, `sawc` was the bug,
and the three slab examples gained `import std.slab.*`. `std.spinlock` turned
out to be the same omission (DF-188i / audit W01) and both are in
`IMPORT_REQUIRED_STD_MODULES` now. The decision needed no ruling in the end —
the spec's own module table already said gated, and the reason it stayed open
was that nothing tied the table to the list. `tools/test_prelude_gate_doc.py`
(`make preludegate`) ties them: every module the table marks gated must be in
the set, and every module in the set must have a row that does not claim
otherwise.

**TWIN (Aug 7, from the user's repo review): `std.spinlock` has the same
hole.** LANGUAGE_SPEC says it is import-gated (`import std.spinlock`), but
`IMPORT_REQUIRED_STD_MODULES` (sawc.py) lists neither `spinlock` nor `slab`
— verified by grep. Unlike slab there is no prelude-by-design reading:
design 149 documented the import, so for spinlock the gate is simply the
bug. Whatever the slab DECISION is, the fix unit should sweep the whole
std directory against the spec's import table so no third twin survives.

### DF-138b — CLAUDE.md's "complete flag set" line is not complete

**OPEN, trivial.** `CLAUDE.md`'s Compiler-usage block says "That is the complete
flag set (`sawc.py:1274-1345`)" but omits `--target-features`,
`--runtime-provider` and `--ids`. Left unfixed deliberately: this brief's scope
on CLAUDE.md was the orientation digest only. One-line fix for whoever is next
in that file.

## Design 150 — Rust-style imports (LANDED, Aug 6)

Closed items: see todo_aug1-aug9.md.

### DF-150 findings (all FIXED in the brief)

- **Not fixed, recorded:** a bare type name from a whole-module USER-module
  import still half-resolves through `_cross_module_lookup`, producing the
  nonsense `cannot assign `Point` to variable of type `Point`` rather than a
  clean "not in scope, did you mean `qmod.Point`". std is unaffected (the
  prelude gate catches it first with the three-form hint, which is what the
  brief's negative test pins). Repro: a `let p: Point = Point(x: 1, y: 2)`
  under `import qmod`. Worth a small follow-up; the fix is to stop
  `_cross_module_lookup` answering for qualified-only imports, which needs a
  check of what else depends on that fallback.

## Design 163 — frame-overlay sizing: the INVESTIGATION REPORT (Aug 7 — user decides)

Closed items: see todo_aug1-aug9.md.

`designs/163-frame-overlay-investigation.md`. Measurement + constraints only; no
layout change shipped. **Lead recommendation: DECLINE the overlay now, land the
tooling, and put design 152's frame-size warning on top of it as the trigger to
revisit.** The reasoning is that the saving is large in theory and ~absent in
this tree, while the cost lands squarely in frame teardown — the code path that
has produced a silent double-free in four separate briefs (124/131/134/146).

### What landed (tooling only — no behavior change)

- **`sawc --emit-frame-layout`** (`sawc/frame_layout.py`, flag in `sawc/sawc.py`,
  mirroring `--emit-ir`'s shape). JSON per monomorphized `__Frame_*`: total ABI
  size + alignment, every field's offset/size/alignment, which fields are
  embedded children (`kind: "sub"`, with the callee frame and the resume state
  the child is live in), plus `own_bytes`/`sub_bytes`, the state count, and the
  spawn-root/method flags. Layout comes from LLVM (`codegen.struct_types` is the
  authority); a `layout_agrees` field cross-checks our C-layout walk against
  `get_abi_size` and was true for all 339 frames measured.
- **`tools/framesizes.py`** — sweeps a corpus, aggregates the distribution and
  top offenders, and solves the overlay recurrence bottom-up. `--only`,
  `--top`, `--json`, `--frame NAME`.
- **Two three-line stashes in `coro_transform.py`** feeding the report:
  `info['drive_state']` in `_emit_nested_call`, and `frame_struct.coro_frame_info`
  at the end of `build_resume`. Read-only; no codegen consults them.

### Unit 1 — reality

Corpus = `examples/` (103 programs contain a suspending function; 339
monomorphized frames). **`blade` and the SOS kernel contribute ZERO frames** —
both are entirely synchronous, so `--emit-frame-layout` reports `"frames": {}`
for each. Two of the brief's three flagship shapes therefore do not exist.

Frame size today: min 32, **p50 72**, p90 432, p99 672, **max 688** bytes; mean
140. Per-task spawn cost (177 spawn-root frames, each a heap box): mean 181 B,
max 688 B.

The shape that decides everything is the **child-count histogram**:

| children | frames | share |
|---|---|---|
| 0 | 271 | 80% |
| 1 | 38 | 11% |
| 2 | 15 | 4% |
| 3 | 15 | 4% |

Overlay can only help a frame with **two or more** children — 30 frames, 9% of
the corpus. Nothing in the tree has more than three.

### Unit 2 — the hypothetical

Every `__subN` is live in **exactly one** resume state. Construction and the
`_goto` into the drive block happen in the same resume tick (`_goto` is a state
assignment + `continue`, never a suspension) and the Done arm moves the result
out and leaves for `after`, so the child's storage is live precisely while
`__state == drive`. The tool CHECKS this rather than assuming it: **zero
violations across all 339 frames**. So the overlay size is a clean recurrence —
`overlay(F) = layout(F's own fields, with the contiguous `__subN` run replaced
by one slot of size max over children of overlay(c))`.

Corpus-wide: **47600 B → 41344 B, 13.1%**. Only 30/339 frames shrink; of those,
median size after overlay is 65% of today. Restricted to the frames that CAN
shrink (>=2 children): 17576 → 11320, **35.6%** (min 25%, max 43%). Spawn roots:
**147 of 177 (83%) are unchanged**; the mean falls 181 → 146 B. Taking each
program's largest task frame (the real per-task heap box): mean **155 → 132 B**,
14.8% across 103 programs.

Top offenders today: `__Frame_recirc` / `__Frame_iflet_shadow` 688 → 400 (42%),
`__Frame_guardlet_*` 672 → 384 (43%), `__Frame_serve` 656 → 424 (35%).

**Flagships.** The accept-loop server (`net_accept_loop_concurrent`) is the
disappointment: `__Frame_server` is **552 → 552, 0%**. It has ONE suspending
call site (`listener.accept()`), and its bulk is a 296-byte `TaskGroup` local,
not children. Its siblings do better — `__Frame_client` 536 → 392 (27%),
`__Frame_handle` (`net_http_roundtrip`) 576 → 432 (25%). Blade's dependency walk
and the SOS root have no frames at all.

**But the corpus understates the model badly.** A synthetic probe
(`.build/scratch/probe_width2.saw`, using `TcpStream.read` as the suspension)
separates the two axes:

| shape | children | today | overlay | saving |
|---|---|---|---|---|
| `w1` — 1 call site | 1 | 272 | 272 | 0% |
| `w2` — 2 sequential | 2 | 496 | 352 | 29% |
| `w4` — 4 sequential | 4 | 944 | 512 | 46% |
| `w8` — 8 sequential | 8 | 1840 | 832 | 55% |
| `d1` — depth-4 chain, 1 call each | 1 | 496 | 496 | **0%** |
| `t3` — branching 2, depth 1 | 2 | 608 | 336 | 45% |
| `t2` — branching 2, depth 2 | 2 | 1280 | 400 | 69% |
| `t1` — branching 2, depth 3 | 2 | 2624 | 464 | **82%** |
| `root` — 6 call sites over the above | 6 | **6768** | **928** | **86%** |

Depth ALONE saves nothing, exactly as predicted — a call chain is genuinely
live at once, so the chain IS the high-water mark. The blow-up is
**branching x depth**: today's flat-frame model is O(k^depth) in a call tree of
branching factor k, the overlay is O(depth). A 6-call-site root over that tree
is **7.3x**. Nothing in the tree today is anywhere near it, but an ordinary
HTTP-handler decomposition (parse -> headers -> body, each calling two
suspending helpers) lands in the `t1`/`root` regime, and Saw boxes one frame
per task.

### Unit 3 — constraints

| # | constraint | verdict |
|---|---|---|
| 1 | `lend` windows (141/146) | **compatible** |
| 2 | state-aware teardown (124/134) | **needs work — the whole cost** |
| 3 | design 158 backtrace tables | **compatible** (gets simpler) |
| 4 | held references / re-borrows (88/106) | **compatible** |
| 5 | DF-138a spawn trampoline | **compatible** (no interaction) |
| 6 | generation-checked slots (134) | **compatible** (no interaction) |

**1. Lend windows — compatible, and the hazard cannot arise today.** A `borrows`
accessor is forced `sync`: `place_transform.py:194-198` sets `decl.is_sync = True`
unconditionally, and `effects.py:698-709` rejects any suspension in it. The
window PARAMETER's type is built `sync` too (`place_transform.py:168-173`,
`:181-184`), and the use site synthesizes a closure checked against it
(`place_uses.py:482-513` -> `effects.py:282-284`), so a suspending call inside a
window is rejected before the coro transform ever runs (place lowering precedes
it and forces a re-typecheck). A `borrows` accessor is therefore never a
coroutine, has no frame, and occupies no `__subN` — a lend window makes ZERO
children live, not two. The brief's "lend-until-epilogue" hazard is real as a
liveness description and vacuous as a constraint. Two riders: nothing pins the
rejection with a test (it is structural, via two independent `sync` gates), and
DF-146k floats `shared borrows` (its `borrows -> &T` alternative is a parse error
since DF-163a's fix) — if that fence is ever lifted this becomes a genuine
two-live-children shape and overlay needs re-verification.

**2. State-aware teardown — NOT state-keyed today, and this is the entire cost.**
`__release` is a flat statement list with no reference to `__state`
(`coro_transform.py:4189-4227`; its one conditional is the `__io_fd >= 0`
reactor disarm), and it deliberately EXCLUDES sub-frames — `_owned_frame_fields`
(`:4170-4187`) documents "each sub-frame releases itself at ITS own Done". Child
storage is reclaimed by the frame struct's MEMBERWISE teardown
(`codegen/resources.py:637-664`, `_emit_field_cleanup_at` recursing into each
`__subN` by STATIC FIELD TYPE), which is also the path a frame torn down WITHOUT
completing takes at group teardown. The whole correctness argument today is
"every owned field's None/Some tag is a valid drop flag at all times": the frame
is fully `StructInit`'d at construction (`_build_frame_init:4267-4316`,
recursively zero-initializing every embedded child) and a completed child left
all its fields None, so re-dropping it is a no-op. Overlay breaks the
*at all times* clause. Three sites need work, all mechanical given each child's
single live state:

  (a) `_emit_field_cleanup_at` must switch on `__state` to pick the live child's
      TYPE — nothing else can, and a shared slot has no single static type.
  (b) `_build_sub_frame`'s rebuild store (`:3789`, through
      `codegen/statements.py:497-509` "LIVE-SLOT RELEASE") drops the slot's prior
      occupant AS THE NEW CHILD'S TYPE — a type confusion the instant two callee
      frames share an offset. The overlay slot must be stored WITHOUT the
      live-slot release; it is known dead.
  (c) `_build_frame_init`'s recursive child zero-init becomes one slot zeroing.
      This is a construction-cost WIN, not just a size one: today spawning a task
      writes the whole sum-sized frame, so `root` above memsets 6768 bytes to
      construct what the overlay would construct in 928.

**3. Design 158 tables — compatible, and simpler.** 158 is a brief, not code, so
the constraint is on the design. Because each child is live in exactly one
state, `(function, state) -> child offset` stays a static function of the state;
under overlay the OFFSET becomes constant (the slot) and only the child TYPE
varies by state — which the table must record anyway.

**4. Held references — compatible; no legal program can observe a reused slot.**
Seeded reference arguments always point from a child OUTWARD into the caller /
task frame (`coro_transform.py:3784-3793`, "a raw pointer into THIS (caller)
frame's storage"; `__recv` likewise at `:3796-3807`) — never sideways at a
sibling, never down into a child. A callee's result is COPIED OUT into a caller
local plus `__saw_forget` before the slot is released (`:3714-3722`). Probed the
one hole the code review flagged, `-> &T`: `return v` on a `&Int` param fails
("expected return type `&Int` but got `Int`"), but `return &v` and
`return &local` both COMPILE (see DF-163a, fixed Aug 7 — a reference return is a
parse error now, so what follows records what the probe found on the day). The
suspending case — the only one
that could aim into a sub-frame — is closed on BOTH paths: spawn rejects cleanly
("local `r` of type `&Int` is a reference held across a suspension"), and the
driven path errors (see DF-163c).

**5/6. Trampoline and generation slots — no interaction.**
`_make_spawn_trampoline` (`:4754-4808`) synthesizes `f$spawnroot` whose sole
statement embeds `__Frame_f`: one child, one drive state, high-water mark ==
sum, so overlay neither helps nor hurts it. The generation counter is
`TaskGroup.gen: Vector<Int>` (`std/taskgroup.saw:278-287`, bumped in
`__recycle:451-458`) with handles as `(slot, generation)` pairs; no
generation state lives in a frame, whose only 134 field is `__cellp`.

### Unit 4 — recommendation

**The brief's suggested cheap partial (branch-arms-only) should be declined on
its own terms.** It was proposed to "dodge the sequential-liveness analysis" —
but the measurement shows there is no such analysis to dodge. Sequential
liveness is already exact and free: the transform stamps each child's single
live state, and it held across all 339 corpus frames with zero violations.
Branch-arms-only would be strictly MORE work (it must distinguish arms) for
strictly LESS saving. The real choice is implement-in-full vs decline.

**Recommend DECLINE now, with a trigger.** The case against implementing today:

- 13.1% corpus-wide, and 80% of frames have no children at all.
- 83% of spawn roots do not move; the mean per-task frame is 155 B.
- The flagship accept-loop server saves **0%** — its bulk is a `TaskGroup` local.
- Two of the three flagship shapes (blade, SOS) have no coroutines whatsoever.
- The cost is concentrated in frame teardown, where a mistake is a silent
  double-free, and where 124/131/134/146 each already found one.

The case for is entirely prospective and rests on the `root` number: the model
is multiplicative where the overlay is additive, so the day a real Saw server
gets a normal handler decomposition, per-task memory jumps by ~7x with no
warning. That is a good reason to make the exponential VISIBLE and a poor reason
to rewrite teardown before any program has hit it.

**So: land the tooling (done), and hang design 152's task-frame-size warning off
`--emit-frame-layout`'s data** — the same numbers, reported at compile time.
Suggested threshold from the measured distribution: warn above ~1 KB (p99 today
is 672 B, max 688 B, so the corpus is silent) and additionally when a frame's
`sub_bytes` exceed its `own_bytes` by more than 2x (the signature of the
branching blow-up; no corpus frame trips it — the >=256 B frames split 45% own /
55% embedded). **Revisit 163 the first time a real program trips either.** The
transform sketch is written down above (three sites, (a)-(c)) so picking it up
later is cheap.

If the user prefers to implement now, the shape is: keep the source-level
`__subN` fields exactly as they are and do the overlay in CODEGEN — emit the
frame struct as `{own fields..., [N x i8] __overlay}` in `_register_struct` and
resolve each `__subN` GEP to the slot. That confines the change to layout +
field addressing + the three teardown sites, leaves `coro_transform` untouched,
and keeps the state-keying in one place. Test plan: an example per child-count
(2, 4, 8 sequential) asserting output AND an `EXPECT-OBJECT-MAX-BYTES`-style
size bound; a cancellation test per shape (the group-teardown path is the one
`__release` does not cover); a loop-carried rebuild test (site (b)); the
`t1`/`root` tree shape end-to-end; and `irdet --all`, since the slot's size is a
`max` over a dict-ordered child set and is exactly the kind of thing design 141
caught being nondeterministic.

### DF findings from the investigation

- **DF-163b — a nested `yield_now()`/`sleep()` silently does not cede.** A user
  helper whose only suspension is a cooperative primitive is treated as
  suspending when spawned DIRECTLY (2 states) but NOT when called from another
  suspending function: the call is emitted as a plain sync call and the caller
  gets one state and no `__subN`. Repro (`.build/scratch/probe_susp3.saw`):
  `func helper(n: Int) -> Int { yield_now()  n + 1 }`;
  `func viahelper(n: Int) -> Int { let x = helper(n)  let y = helper(x)  y }`;
  `group.spawn(viahelper(1))` -> `__Frame_viahelper` has `states: 1`,
  `children: []`. `group.spawn(helper(1))` -> `__Frame_helper` has `states: 2`.
  Same for `sleep`. The program runs and prints the right answer — it just never
  yields, which is the "never silently block" contract design 96/101/104 exist to
  hold. A std suspending METHOD (`stream.read()`) propagates correctly through
  the same nesting, so this is specific to the cooperative free-function
  primitives. **Worth its own brief** — it also means the corpus measurement
  above UNDERSTATES the child population: fix this and more frames gain children.
- **DF-163e — CLOSED BY RULING, note for whoever picks up DF-146k.** DF-146k
  floats `shared borrows` *or* `borrows -> &T` as spellings for a shared-flavor
  place. `borrows -> &T` is now a parse error like any other reference return, so
  `shared borrows` (or an equivalent that never names a reference) is the only
  live candidate. Nothing to do unless 146k is taken up.

## Design 160 — remote test worker (LANDED, Aug 6)

Closed items: see todo_aug1-aug9.md.

- **DF-160d — the daemon's silent console costs operator confusion (Aug 7,
  from the user's first Studio deployment attempt).** The user saw /health
  answer (core count reached the client) and concluded nothing was happening
  remotely, because a healthy job shows NOTHING on the worker's console — job
  output goes to per-job log files and per-request HTTP logging is
  suppressed. Follow-up: a `--verbose` console mode (request lines + job
  lifecycle + a pointer to the live log path at job start), and the startup
  banner should print WHERE job logs will appear. Small unit, rides any 160
  follow-up. The user's deployment investigation is still open — first real
  sandbox application (DF-160a below) also still pending.
- **DF-160a — the sandbox profile could not be APPLIED during development, only
  compiled.** A process already inside a seatbelt sandbox cannot apply a second
  one: `sandbox_apply` returns EPERM, so `sandbox-exec` fails outright from
  inside a sandboxed agent (and `launchctl submit`, the obvious escape, is
  unavailable). Everything else in the design was validated against a live
  loopback worker; the profile was validated by COMPILING it through
  libsandbox, which resolves every operation and filter name against the
  running kernel and rejects a profile naming one that does not exist (proven
  by a negative case in the self-test). What remains unproven until the user
  runs it on the Studio is whether the allowances are SUFFICIENT — a denial
  would show up as a job that fails where the same job passes locally. The
  daemon's startup line reports `sandbox: ACTIVE`, and the first
  `remote_battery.py` run against the real machine is the check. If a gate
  fails there and not here, the profile is the first suspect: `log stream
  --predicate 'sender == "Sandbox"'` names the denied operation.
- **Follow-ups, not blocking.** (a) SOS stays local — QEMU on the worker is
  the opt-in the brief deferred. (b) One job at a time; a second client
  degrades rather than queues, which is right for two machines and would want
  revisiting for three. (c) The worker keeps `.build/rt` between jobs keyed by
  a digest of `sawc/`; nothing else survives a job, so a compiler-touching
  brief pays one runtime build per submission.

## Design 151 — discarding a `Result` is an error (LANDED, Aug 6)

Closed items: see todo_aug1-aug9.md.

- **DF-151m — FILED, NOT FIXED (typechecker; found while fixing DF-151j,
  Aug 7).** **`&var` into a projection rooted at a `let` binding compiles and
  mutates — the `let` promise is broken for fields, tuple elements AND fixed
  array elements alike.**
  ```saw
  func bump(x: &var Int) { x = x + 1 }
  let p = Pair(a: 1, b: 2)
  bump(&var p.a)
  print("{p.a}")            // 2 — no error, and the `let` was written through
  //                           `p.a = 2` on the same binding IS rejected
  ```
  PRE-EXISTING and not tuple-specific; tuples inherit it because DF-151j made
  them consistent with fields, which is the correct outcome for that unit and
  the reason this is filed rather than fixed there. `_check_reference_expr`
  checks `&var` mutability for an Identifier operand, for `self`, and for a
  projection out of a `&self` receiver (`_projects_from_self`, DF-146b) — but
  there is no arm for a projection rooted at a LOCAL, so the walk
  `_assign_target_immutable_struct_root` already performs for every assignment
  target is simply never run on a reference operand.
  Expected shape: run that same walk in `_check_reference_expr` when
  `expr.mutable` and the operand is a projection, with the message the
  assignment path gives. Blast radius is why it is its own unit — the rule
  reaches every `&var` into a field or element in std, blade and the libs, and
  any legitimate one written through a `let` root today becomes a compile error
  that has to be re-spelled `var`.
- **DF-151k — FILED, NOT FIXED (typechecker; found while fixing DF-151i,
  Aug 7).** **`type_satisfies_copy_bound` has no OPTIONAL and no TUPLE arm, so a
  fixed array of either is refused `.copy()` even when the element tier provides
  one.**
  ```saw
  let a: [Arc<Res>?; 2] = [...]
  let b = a.copy()
  // error: type `[Arc<Res>?; 2]` is not Copy; its element type is not copyable
  // ... and the same for `[(Arc<Res>, Int); 2]`
  ```
  Both messages are false: `Arc<Res>?` and `(Arc<Res>, Int)` each report an
  'implicit' `copy_tier`, and `o.copy()` / `t.copy()` on those very types
  compile. The array arm of `_check_copy_call` is the only `.copy()` path that
  consults `type_satisfies_copy_bound` instead of `copy_tier`, and that
  predicate answers structurally for ARRAY and FUNCTION and then falls to a
  NAME lookup — an optional and a tuple have no name, so both return False.
  Only NON-trivial element payloads are affected: `[Int?; 2]` and
  `[(Int, Int); 2]` copy fine, caught by the `is_trivially_copyable` test at the
  top, which is why this sat unnoticed.
  Shared by two wrappers, so it is not tuple-specific and was left out of
  DF-151i deliberately — the surface there was the `.copy()` arm, and
  `type_satisfies_copy_bound` also gates generic `T: Copy` bounds, giving a fix
  a wider blast radius than that unit's scope. Expected shape: give it the two
  structural arms its ARRAY arm already models (a wrapper satisfies the bound
  iff its payload/elements do), then re-check what widening the `T: Copy` bound
  admits — `Vector<(Arc, Int)>.iter()` becomes legal, which is correct per
  design 139 but should land with a test.
  Repro noted in `df151i_tuple_copy.saw`, where the array-of-tuples case is
  commented out rather than written.
- **DF-151g — FILED, NOT FIXED (codegen; found while fixing DF-151d, Aug 6).**
  **A `_`-discarded NoCopy payload in a match arm never runs its deinit.**
  ```saw
  enum Slot { case Filled(r: Res), case Empty }   // Res is NoCopy with a deinit
  match filled() { case Filled(_) -> 1, case Empty -> 0 }   // Res.deinit never runs
  ```
  Deliberate, and deliberately wrong for this case. `match.py`'s design-65 (L17)
  branch releases a `_`-bound owning payload with `_emit_release_at`, which
  RELEASES a refcounted field but leaves a non-refcounted `Deinit` one untouched
  — because `Map._slot_state`'s `Occupied(_, _)` peek matches a by-value,
  NON-RETAINED copy of a slot the map still owns, and firing the payload's deinit
  there would destroy the map's live value. So the same code serves an OWNER and
  an ALIAS, and it can only be right for one.
  Same for a NAMED local (`let s = filled(); match s { case Filled(_) -> ... }`),
  so it is not about DF-151d; an `Arc` or `String` payload is unaffected (the
  release is the whole drop). The real fix is upstream: `Map._slot_state` should
  read its slot through a BORROW rather than a by-value copy, at which point the
  consume path stops seeing an alias and this branch can become a full
  `_emit_drop_at`. Doing it the other way round — changing the release to a drop
  first — would break the design-61 exactly-once VALUE tests, so the order
  matters. `examples/df151d_match_temporary_scrutinee.saw` measures an
  `Arc<Res>` payload for exactly this reason; a bare NoCopy payload would have
  read as a leak that is this finding, not that one.

## Design 149 — runtime authoring in Saw (LANDED, Aug 6)

Closed items: see todo_aug1-aug9.md.

**Not in v1:** a non-trivially-destructible static (statics stay deinit-free);
relaxed/acquire-release orderings on `Atomic` or `SpinLock` (everything is
seq_cst); a `SpinLockIrq` for the same-core ISR case, which the brief assigns to
sos-side composition when M2-era interrupt work lands.

## Design 145 — DF-findings (enum methods; the std private-symbol reach)

Closed items: see todo_aug1-aug9.md.

- **DF-140h-fn — OPEN, stopped deliberately (unit A, design 145). Wants its own
  brief.** The same reservation exists for private std FREE FUNCTIONS, and the
  fix is a materially bigger change than the statics half. Repro:

  ```saw
  func tcp_socketpair() -> Int { 77 }   // private in sawc/std/net.saw
  func main() { print(tcp_socketpair()) }
  // error: function `tcp_socketpair` is already defined with an
  //        indistinguishable signature
  ```

  Also `unix_timestamp` (std/time.saw — which is separately worth a look: it is
  a DOCUMENTED std.time API function declared without `public`). The
  `__saw_exec_*` family in std/taskgroup.saw is worse than reserved: redefining
  one reports `internal compiler error: Undefined function: __saw_exec_run`
  rather than any diagnostic.

  Why it did not land with the statics half: statics have one identity (a name),
  so a per-module overlay is contained. Functions carry OVERLOAD SETS, and
  design 55/66/105 built the `$OL$` symbol scheme assuming one flat set per
  name. Filtering the set by accessor module was tried and gets the front end
  right, but two same-named functions from mutually-invisible modules then reach
  codegen as one overload set and ICE (`internal compiler error:
  tcp_socketpair$OL$`). Doing it properly means making overload-set IDENTITY
  module-scoped — a per-module overlay for private functions, a std-side
  symbol-stamping pass (`_stamp_module_private_functions` runs only from
  `check_module` and guards on `def_module == own_module`, so std never reaches
  it), and a decision about whether a module's private function overloads with a
  public one visible in that module. That is a design question design 145 does
  not settle, so the front-end change was reverted rather than landed half-done.

## Design 137 — DF-findings (fixed-capacity formatting)

Closed items: see todo_aug1-aug9.md.

- **DF-148b — FILED (design 148, found writing `std/fixedbuf.saw`). A `static`
  is not readable from a `static_assert` condition**, so a threshold used in one
  has to be a literal even where the codebase has a name for it
  (`static_assert(N >= 5, ...)` in `FixedStringBuilder.init`, where
  std.stringbuilder calls the same number `MIN_FIXED_CAPACITY`). This collides
  with the no-magic-numbers style rule. The evaluator now HAS an identifier arm
  (design 148 gave it one for const parameters), so the fix is small: admit a
  `static` whose initializer is itself const. The comment at
  `codegen/core.py:1562` already claims statics are emitted first "so
  const-static references resolve" — it was aspirational.

- **DF-148a — FILED (design 148 unit B). A repeat literal cannot repeat a
  GENERIC element, because no bound expresses "copies are free".** `[t; N]`
  where `t: T` is refused: `T: Copy` admits ExplicitCopy (which needs a
  `.copy()` per slot, and a repeat has nowhere to write one), while
  `T: ImplicitCopy` excludes the POD types that are freer still — so `Int` fails
  an `ImplicitCopy` bound and the natural `Ring<T, const N: Int>` is unwritable.
  The element type is concrete in v1 and the error says so. Two ways out worth
  deciding between: a bound that means trivial-or-ImplicitCopy, or letting
  `T: Copy` through and emitting a per-slot `copy()` in codegen (which is what
  the splat loop already does for the retain case). Not urgent — the acceptance
  shape `FixedBuf<const N: Int>` has a concrete `UInt8` element — but it is the
  first thing anyone writing a generic container will hit.

- **Follow-up (not a bug): the `{}` Printable scratch is per call site.** Each
  user-`Printable` format argument gets its own 512-byte entry alloca, because
  every segment of a `panic` message is built before any is concatenated — two
  arguments sharing one buffer would print the second value twice
  (`format_args_panic` pins this with two of them). Across SEPARATE format calls
  the buffers could be shared, since each call consumes its segments before the
  next runs, so a function with N such arguments costs N x 512 bytes of stack
  where it could cost (max args in one call) x 512. Not pooled here: the win is
  bounded and the failure mode of getting it wrong is silent wrong output. Worth
  doing for the embedded profile, ideally alongside LLVM lifetime intrinsics so
  stack coloring can do it rather than the frontend.

## SOS M1 — design 140 (BUILT, branch PARKED for user review)

riscv32 boot-to-root-server. `make sos-test` is 11 cases; the two-image boot
prints kernel banner -> root banner -> clean exit. SOS-review policy applies:
the branch is NOT integrated without explicit user sign-off.

> **SUPERSEDED BY THE ADOPTION PASS (Aug 6).** The branch to review is now
> `worktree-agent-ae0afeb4057ec52bc` — this work rebased onto main at bbdb2e3
> and modernized to designs 139-161. The original parked branch
> (`worktree-agent-a45480eb72c6ab0f1`, 8b027c7) no longer compiles against
> current main. See "SOS M1 — the adoption pass" below for the rebase conflicts,
> what changed, and the open questions. Everything in THIS section still
> describes the design; only the spellings moved.

REVISED after the first user review (five items + a rebase onto designs
132/133). The numbered-syscall pin below is SUPERSEDED by the object-op model.

**Pins TAKEN as written.** Syscall ABI per §5.7: a0 = HANDLE, a7 = OP, args
a1-a5, returns a0 = status / a1 = value, and EVERY syscall is an object op
(ratified Aug 5) — the earlier `0 debug_putc` / `1 exit` numbered table is
gone. The v1 object is the **System** singleton with ops `debug_print` and
`shutdown(status)`, rights-gated on DEBUG / SHUTDOWN; `exit` is deliberately
absent because process exit belongs to the future Process object. Dispatch is
§3's shape verbatim: handle-table lookup -> object type -> op table -> rights
check -> op. Root receives the System handle at boot (§12), in the first
argument register, so a Saw `_start(boot_handle: UInt)` just takes it. sosimg
magic `SOSI`, u16 version = 1, u8 segment count, the u32 §7 priority-map field,
all fixed-width little-endian (design 47). Root as an APPENDED BLOB after the
kernel image with linker-symbol bounds (`.payload`, `_payload_start` /
`_payload_end`) rather than a flash partition table. `[sos]` manifest section
driving a Blade `emit = "sosimg"` target. A U-mode fault or a malformed image
prints a cause tag and exits FAIL — M0's never-hang discipline kept throughout.

**Round 3 — API ownership (spec §5.7's vDSO discipline, ratified Aug 5).**
The typed wrappers moved into a PUBLIC `sos` module owned and exported by the
kernel package (`sos/kernel/sysapi/`, U-mode library code living in the
kernel's tree). Every op number, rights bit and status tag lives in ONE
kernel-internal package (`sos/kernel/abi/`) imported by BOTH the kernel's
dispatch tables and those wrappers, so the two halves of the contract cannot
skew and the kernel may renumber freely. Root dropped its own wrapper and stub
knowledge entirely and imports `sos` as a path dependency; a grep for an op
name across `sos/root/`, `sos/hal/` and `sos/tests/faulting-root/` sources
returns nothing. The kernel package also `@export`s a per-op C-ABI surface
(`sos_system_debug_print`, `sos_system_shutdown`) over the fixed-arity raw
`sos_syscall1` over the per-arch `ecall` stub — one implementation chain, three
entry altitudes (typed Saw, typed C, raw), with the Saw wrappers riding the
same chain rather than a second trap path. The user HAL's own runtime sinks
call the typed C surface, so the C altitude is exercised on every boot instead
of only being linked; root additionally calls `print` once, which runs the
whole C chain and demonstrates design 137's alloc-free formatting inside a
U-mode process. Each seam doc gained a short note saying which altitude is
supported for whom.

**Structure the revision landed** (review items 1-5):
- The format is a SHARED package, `sos/imgformat/` — the two structs, the
  constants, the `static_assert` ABI pin, and the target-independent
  well-formedness predicates. Consumed by BOTH sides and by both mechanisms:
  Blade through a manifest path-dependency, the kernel through
  `--module-path`. Kernel-specific bounds (ROOT_LOAD_BASE, the PMP budget)
  stay kernel-side.
- The kernel loader reads through TYPED VIEWS — `UnsafeMemory<SosimgHeader,
  Normal>(addr).read()`, then `seg.mem_len` — not offset arithmetic. The whole
  offset-constant family is gone. The validation logic and its overflow-careful
  order are unchanged; only the fetches are.
- Blade's byte helpers are a module-PRIVATE `extension Data`, called as
  methods. Being private is load-bearing: `blade/tests/sosimg_wire.saw` cannot
  reach them and brings its own reader, so a bug in the helpers cannot cancel
  itself out.
- `sos/rt/common/` (Saw, arch-free and role-free) + `sos/rt/common_c/support.c`
  (the C that must stay C, once) + `sos/hal/riscv32/{kernel,user}/` with an
  ABI.md per side. The ~200 duplicated lines across the two rt.c files are
  gone. NO arm64 directories were created: M1b adds them without moving
  anything.
- `[sos] native` is a space-separated LIST pointing into the HAL, so a root
  package's own sources name no architecture.
- Lockfiles committed for `sos/root` and `sos/tests/faulting-root` (app policy).

**Pins ADJUSTED (each veto-able; reasons given).**
- **sosimg field order + padding.** Header fields are ordered and padded so
  every u32 sits on a 4-byte boundary: magic(4), version(2), seg_count(1),
  reserved(1), entry(4), prio_map(4) = 16 bytes, then the segment table. The
  brief's order put `entry` at offset 6. Alignment is what lets the kernel's
  loader read the header with plain word loads instead of byte assembly.
- **`entry` is an absolute load address, not an offset.** Nothing relocates on
  Profile A (physical addresses, PMP not paging), so an offset would only be a
  base-addition the kernel has to perform and validate. Root is linked at a
  fixed address by root.ld either way.
- **Each segment record carries `mem_len` beside `file_len`** (20-byte record,
  not 13). The pinned record cannot express a segment whose memory image
  exceeds its file image, so a loader built from it could not zero-fill `.bss`
  — and root's `.bss` is a 4 KiB arena. The kernel zeroes `[file_len, mem_len)`.
- **`[sos] native = "<file>"` added** (not anticipated by the brief). A
  freestanding SOS process needs an `ecall`, which no amount of Saw expresses;
  root's `src/rt.c` is the syscall stubs plus the `__saw_rt_*` seams, the same
  minimal-native-surface shape as `sawc/rt/shim.c`. One translation unit.
- **PMP budget = 4 TOR regions** (8 of QEMU's 16 entries): up to 3 image
  segments plus the kernel-granted stack. Root links to 2 segments (R+X,
  R+W), so there is one spare. An image asking for more is rejected as
  malformed rather than silently under-protected.
- **Root region pinned at 0x8020_0000..0x8024_0000** (256 KiB) with a 16 KiB
  stack at the top, recorded in virt.ld's memory map and mirrored by root.ld.
  The kernel VALIDATES rather than assumes, so a mismatch is a diagnostic.
- **`boot_smoke` became `no_root_image`.** The kernel now requires a root
  image; built without one it must say so and FAIL, not exit 0 as if the
  system had run. The M0 banner assertion moved to the two-image case.
- **`debug_print` carries ONE CHARACTER in a1, not a (ptr, len) pair.** Passing
  process memory to the kernel needs bounds machinery that belongs with
  MemoryObject — the kernel would have to know which ranges the caller was
  granted, which is Process-object state M1 does not have. One character per
  op is seL4's `DebugPutChar` shape and keeps the op honest about what it can
  check. The typed wrapper hides it: root writes `system.debug_print(msg)`.
- **`umode_bad_syscall` became `umode_bad_calls`** and inverted. Under the
  object-op model a bad op or a bad handle is an ERROR, not a fault: the kernel
  returns a `SysError` status and the process runs on. The payload now checks
  three statuses itself (OK on a valid call, BAD_OP, BAD_HANDLE) and shuts down
  with 7 only if all three matched, so the emulator's exit code is the
  assertion.

**Bug found and fixed while revising (standing fix-on-discovery policy).**
`blade build` exited 0 on a failed build — only `blade test` ever called
`exit()`, so every other command printed `error: ...` and reported success.
A stale `sos/root/Saw.lock` therefore produced a "successful" build that
silently shipped the PREVIOUS image, and the SOS suite booted it without
noticing. Every failing path in `blade/src/main.saw` now exits non-zero
(carrying `BuildError.exit_code` where there is one), and `sos_runner.py`
deletes an existing image before rebuilding so a stale artifact cannot stand in
for a fresh one.

**Open / deferred.** The parsed `prio_map` is reported on the console but not
yet STORED — there is no Process object until the object-model brief (§7 says
the kernel stores whatever map the launcher passes; root's is applied
verbatim). The kernel's `__atomic_*_4` bodies in `sos/kernel/rt.c` and
`sos/root/src/rt.c` are plain read-modify-write, correct ONLY because v1 is
uniprocessor with no interrupts enabled (spec §7); enabling interrupts or SMP
must replace them, and building the Saw object for `rv32ia` would retire them.
A singleton `static` driver still awaits Once/Lazy (tracker F5), so `console()`
constructs its `Uart16550` per use.

## SOS M1 — the adoption pass (Aug 6, branch RE-PARKED for user review)

**Branch: `worktree-agent-ae0afeb4057ec52bc`.** The parked M1 branch
(`worktree-agent-a45480eb72c6ab0f1`, 8b027c7) rebased onto main at bbdb2e3 and
brought up to the rules that landed while it sat — designs 139-161. SOS-review
policy still applies: NOT integrated without explicit user sign-off. `make
sos-test` is 11/11 and the full battery is green (numbers at the end).

**The rebase.** Seven M1 commits over 118 commits of main, four conflicts, all
in shared plumbing rather than in SOS logic:

- `sos/kernel/main.saw` — main's design-135 commit edited comments in the M0
  kernel body that M1's unit A had already moved into `core/lib.saw`. Took M1's
  structure; the design-135 substance (the sos gate builds under
  `--no-hidden-alloc`) survives in `sos_runner.py`, whose comment says it.
- `tools/sos_runner.py` (twice) — main added `--no-hidden-alloc` to the compile
  line, M1 added `--module-path kcore=...` and the payload-object list. Both
  wanted, so both kept.
- `.gitignore` / `Makefile` — additive on both sides. One real decision:
  M1's own internal-rebase commit had already DELETED its `*.sosimg` ignore
  rules because design 143 moved Blade artifacts under `<package>/.build/`, so
  the deletion is what survived, alongside main's worker-jobs and fixture-lock
  rules.

**Two compiler bugs, found by writing the adopted idioms and fixed here.** Both
have regression tests in `examples/` and are why the branch touches `sawc/`.

- **DF-140j — a place use inside a struct or map literal reached codegen
  unlowered (ICE).** `place_uses._recurse` tested each list item for
  `Expression` then `ASTNode`. `StructInit.field_inits` is `(field_name, value)`
  and `MapLiteral.entries` is `(key, value)` — plain tuples, neither test — so
  the expressions inside them were never walked and a `borrows` accessor in
  those positions met codegen raw: `internal compiler error: Undefined method:
  Holder.at`. `let` and argument positions worked, which made it read as a
  module-boundary problem for a while. `_recurse` now descends into a tuple item
  through `_paired`. Test: `place_paired_literal_fields.saw`.
- **DF-140k — an extension method's parameter types were never resolved.** The
  parser gives every bare named type a STRUCT kind and only resolution knows
  which names are enums. A plain function has always resolved its parameters
  before binding them; an extension method did so only for a module-QUALIFIED
  annotation (design 68's L18 fix). Nothing noticed until a backed enum met
  design 145's cast, which looks for ENUM kind: ``cannot cast `Right` to
  `UInt` `` inside a method, with the identical cast compiling in a free
  function. The binding now resolves either way; the write-back to `param.type`
  stays qualifier-only, which is what the original comment was protecting.
  Test: `backed_enum_extension_param.saw`. Found because the rights check is
  `entry.allows(Right.Debug)` — an enum parameter cast inside a method on the
  receiver, i.e. two of design 153's idioms at once.

**A safety finding that changed a brief item — worth the user's attention.**
The adoption list asked for `imgformat`'s `SegFlags` to become "a backed-enum
FIELD in the typed header view". It should not, and the measurement is short:

    a wire byte of 6 (W|X — a combination `has_sane_perms` rejects), overlaid
    through `UnsafeMemory` on a struct whose field is a backed enum, read back
    as the FIRST case and matched its arm silently.

`SosimgSeg` is overlaid on bytes the loader did NOT produce. An enum-typed field
mints an enum value straight from an attacker-chosen byte with no `from(raw:)`
between them, and a `match` on a value naming no case still selects an arm — so
the kernel would install a PMP region from a permission it never validated. The
bits became `SegFlag` and the mask field stayed a raw `UInt8`, with `has` /
`has_sane_perms` as the validating boundary.

The general rule this suggests, for the skill's wire-idiom section: **a backed
enum is safe as a wire-struct field only when the producer is trusted. Anything
PARSED keeps its raw integer field and exposes a `from(raw:)` accessor.** The
skill currently shows `flags: SegFlags` as the idiom with no such caveat.
Flagged rather than edited — the skill is another agent's surface tonight.

**What was adopted.**

- **145-C, the syscall ABI.** `sosabi`'s four families of parallel `static
  UInt`s became backed enums. `SysOp.from(raw:)` retired `OP_SYSTEM_MAX`: the
  range check and the decode are one step now, and the dispatch is an exhaustive
  `match`, so a new op fails to compile until handled. It is backed by `UInt`,
  the width of the register the op arrives in, because a7 is PROCESS-CONTROLLED
  — a narrower backing would need a truncation first, and `0x100` would arrive
  as a valid `DebugPrint`. Verified `from(raw: 0x10000)` is None.
  The status enum is backed `UInt8` (its tags cross the trap boundary; design 47
  pins the width) and gained `describe()` + `Printable` + `Error`, which retired
  the free `sys_error(status)` helper. Because conformances must live with the
  type (orphan rule), the enum MOVED from `sysapi` to `sosabi`, so both halves
  of the contract now compile from one declaration. A process still never
  imports `sosabi` — checked with a two-module probe that it can interpolate the
  error and match its cases through the value alone.
  `Right` and `ObjType` complete the set; the mask arithmetic moved into
  `HandleEntry.allows(Right)`, and `ROOT_SYSTEM_RIGHTS = 3 // DEBUG | SHUTDOWN`
  became `root_system_rights()` (a function, because a static initializer takes
  plain literals and a `3` with a comment naming its bits is the magic number
  the pass exists to remove). (`Right` became the per-kind `SystemRight`, and
  the check moved onto a validated-handle type, in the review round below.)
- **145-C, the image format.** `SEG_FLAG_*` became `SegFlag`, per the finding
  above. The hand-assembled test payloads (`sos/tests/payload_*.S`) keep their
  own `.equ SEG_FLAG_R, 1` and status literals, unchanged and on purpose: they
  exist to pin the format independently of the Saw definition, so that two
  producers agree with one loader. Renumbering `SegFlag` would need them edited
  too, and nothing enforces that — which is the price of the independent check,
  and was equally true when the Saw side was statics.
- **146, the toml API.** `TomlDoc.get_section` is gone (it handed back a
  non-retained alias — DF-132a), so `blade/src/sosimg.saw`'s `[sos]` reader
  searches once with `index_of` and reads through `section_at` windows, the
  shape `manifest.saw` already used. `band_level` became an extension method on
  `TomlSection` rather than a free function taking `&TomlSection` — a question
  about a section reads as one, and a method call is also the single expression
  a place window wants.
- **153, the kernel's own families.** `TrapCause` (nine `CAUSE_*` statics, and
  with them `cause_tag`'s nine-branch if-else — the hardware CAN raise a cause
  the kernel does not model, so `from(raw:)` names that miss and the rest is
  exhaustive), `PmpPerm` (the third bits/mask instance, spelled like `Right` and
  `SegFlag`), and `ExitCode`, which is now `fatal`'s parameter type instead of a
  bare `UInt` in the position the harness asserts on.
- **Stale prose.** `rt.c` has not existed since design 140's revision split it
  into `sos/hal/riscv32/kernel/sink.c` and `sos/rt/common_c/support.c`; five
  places still described an image as `boot.S` + `rt.c`, including the kernel
  entry header and the runner's pipeline listing.
- **A workaround main fixed.** `sos/rt/common` named its digit constants
  `HEX_ASCII_ZERO` etc. to dodge DF-140h (a private std static reserving its
  simple name program-wide). Design 145 unit A fixed that, so they are
  `ASCII_ZERO` / `ASCII_LOWER_A_MINUS_TEN` again.

**What design 149 had NO target for, and why — checked, not skipped.**

- **Zero regions.** Already right, and already at real size: the 64 KiB kernel
  stack and the 128-byte trap frame are `.bss` reservations in `boot.S`, which
  is where they belong. No Saw declaration wants to become one.
- **`SpinLock`.** Nowhere, as the brief predicted. rv32 M1 is single-hart AND
  the kernel holds no mutable global state in Saw at all — the handle "table" is
  a comparison against one constant, deliberately, until the object model. Not
  forced.
- **`unsafe static var`.** Same reason: there is no compound static using a
  workaround, because there is no compound static.

**The one real design-149 opportunity, NOT taken here — the top item for
review.** `sos/rt/common_c/support.c` gave three reasons it had to be C. One is
permanent: a Saw byte-copy loop is what LLVM's loop-idiom pass rewrites into a
call to `memcpy`, which in a freestanding build IS this memcpy, so mem* stays C
under `-fno-builtin`. The other two WERE DF-140g, which design 149 closed:

  1. the arena needed mutable module state and a `.bss` reservation —
     `unsafe static var` plus a zero-initialized `static ARENA: [UInt8; N] =
     [0; N]` (zerofill in both profiles) now express it;
  2. the seams needed to `@export` reserved `__saw_rt_*` names —
     `sawc --runtime-provider` (Blade: `[package] runtime = true`) now allows it
     from an ordinary freestanding build, with each signature checked against
     `sawc/rt/ABI.md`.

So the arena and the four seams COULD be Saw today, and SOS is precisely the
case design 149 was built for. Not done here because it changes the allocation
and panic paths of the kernel and every process image at once — a deliberate
decision, not an adoption sweep. The file's comment now says this instead of
citing the closed gap. Note the build-path split when scoping it: the ROOT
packages are Blade packages and would use the manifest key, while the kernel is
built by `tools/sos_runner.py` invoking sawc directly — but `--runtime-provider`
is a plain sawc flag, so the kernel needs no move to Blade to adopt it.

**Open questions for the user.**

1. **The runtime migration above** — worth its own brief, or fold into M1b?
2. **`Unknown` lost its payload.** (The type is `SosStatus` since the review
   round below.) The old enum had `Unknown(status: UInt)`, carrying the
   unrecognized number; a backed enum is payload-free, so `Unknown` is now a
   plain case (255 — not a value the kernel returns) where the userspace
   `from(raw:)` miss lands. In M1 it is unreachable (both halves compile from
   one table) and no caller printed the number, so nothing regressed today. If a
   diagnostic should carry the raw tag later, that wants a struct error or a
   companion field, not a backed enum.
3. **The wire-enum caveat** for the saw-lang skill (above).
4. **The status enum living in `sosabi`, a KERNEL-INTERNAL package**, is a
   slight tension with that package's "nothing else imports this, ever"
   charter. It is forced by the orphan rule and it costs userspace nothing
   (verified), but the module docstring's claim is now narrower than it reads.
   The review round below put `SystemHandle` there for the same reason — one
   declaration the dispatch and the wrappers share — so the tension is now
   structural rather than incidental, and worth a line in the charter if the
   package grows a third resident.

**A gate-coverage note worth keeping.** The `SegFlag` rename swept `sos/` and
`blade/src/` but missed `blade/tests/sosimg_wire.saw`, and NOTHING in the usual
loop noticed: `test_runner.py` does not compile `blade/tests/`, so the suite,
lexdiff, astdiff, irdet and sos-test were all green with blade's own suite
broken. The only gate that runs `blade test` is the bootstrap, which is why a
brief's final battery has to include it rather than treating it as optional.

It nearly escaped anyway, through a harness bug of mine rather than a repo one:
the first battery script piped each gate into `tail`, so `$?` was `tail`'s status
and every gate looked green. Rewritten to capture each gate's real exit code and
report a FAILED list. Worth stating because the same shape would hide any gate
failure, not just this one.

**Gate battery** (re-run strictly, against the final tree). Full compiler suite
1343 green (1341 at the branch point plus the two regression tests above);
lexdiff zero mismatches; astdiff clean over 1499 files; `irdet --all` byte-
identical over 883 examples; abidoc 53 seam signatures matching the frozen set;
blade bootstrap `BOOTSTRAP: ok` (stage0->stage2, 21/21 twice + the lib suites);
gmgate 12 programs x 10 runs, 0 failing; `make sos-test` 11/11 under QEMU.

## SOS M1 — the review round (Aug 7, branch RE-PARKED for user review)

**Branch: `worktree-agent-a6dd63281e227ac66`.** The adoption-pass branch rebased
onto main at 9cd0f8f (clean; two of its DF-fix commits were already upstream and
dropped as duplicates) and the FOUR review-round changes applied. All four were
**ratified by the user on Aug 7** and written into `sos/spec.md` (§3 and §5.7
item 7) before any code moved; this pass implements what those sections say.
SOS-review policy still applies: NOT integrated without explicit user sign-off.

**The four changes.**

1. **Typed handles.** `type SystemHandle = UInt` in `sosabi`, taken by the
   Saw-facing wrappers and by the kernel's op layer. The distinct alias gives
   the wanted asymmetry for free: it flows TO `UInt` implicitly, and a raw word
   or another kind's handle cannot flow in. Two sites cross INTO the type —
   userspace adopting its boot handle, and dispatch after the table resolved the
   handle — which is what makes it mean "validated as System". The typing stops
   at the ABI boundary: `@export`ed symbols and `sos_syscall1` keep raw words.
2. **`SysError` -> `SosStatus`.** A status with an `Ok` case is not an error, and
   the `Sos` prefix separates it from the hosted runtime's own frozen `SysError`
   (`sawc/rt/ABI.md`), which is untouched. Cases keep their values.
3. **Kind-scoped rights.** `Right` -> `SystemRight: UInt32`, and the check moved
   onto `SystemObject` — the pairing of a validated handle with its rights word
   — so `allows` takes a `SystemRight` and nothing else.
4. **The universal low byte.** Bits 0-7 identical in every kind's enum (0
   Transfer, 1 Manage, 2-7 reserved); kind rights from bit 8. `static_assert`s
   pin it against the enums themselves.

**The lowering, verified rather than assumed.** The brief asked for one checked
lowering; both halves were read out of `--emit-ir`:

- Userspace: `%boot_handle` reaches `sos_syscall1` as itself. No `zext`, no
  `trunc`, no `bitcast`, no temporary — the construction, the `System.handle`
  field and the flow back out to a `UInt` parameter all lower to nothing.
- Kernel: `SystemObject` never materializes (no alloca, no insertvalue), and the
  rights check against root's constant mask folds away entirely.

So tier one of the handle model costs zero instructions in both directions.

**Three compiler gaps, found by writing the ratified idioms and fixed here.**
Each has regression tests in `examples/`, and each BLOCKED a ratified change
rather than merely inconveniencing it — which is why the branch touches `sawc/`
at all. Filed as DF-140l/m/n below.

- **A backed enum's case was not a compile-time constant**, so change 4 could not
  be written: `static_assert((SystemRight.Transfer as UInt32) == 1, ...)` was
  rejected, and the only way to assert anything about a wire table was to
  transcribe its numbers into the assertion — which is what an assertion exists
  to make unnecessary.
- **Distinct aliases had no constructor**, so change 1 could not be written.
  `UserId(42)` — the form LANGUAGE_SPEC documents and the `42 as UserId`
  diagnostic points at — was `undefined function`. The only spelling that
  produced an alias value was an annotated `let`, which accepts an underlying of
  just the four primitive kinds, so `type SystemHandle = UInt` had no way to be
  given a value AT ALL.
- **Sibling aliases flowed into each other**, which would have made change 1
  cosmetic. `let order: OrderId = user` compiled, and so did passing a `UserId`
  where an `OrderId` was expected; only the sibling CAST was rejected. A typed
  handle is a safety property exactly to the extent that another kind's handle
  cannot land in it, so this was the one that mattered most.
  - A fourth, found while fixing the third: **an IMPORTED alias was not treated
    as an alias**, so it neither flowed nor constructed one module away from its
    declaration, while annotations using it checked fine.

**Two notes for the user.**

1. **LANGUAGE_SPEC's Type Definitions section described three things that did not
   work** — the constructor, the sibling rejection, and `Float64`, which is not a
   type this compiler has at all (only `Float`). The first two now work and the
   section was rewritten against tested snippets. `Float64` was left alone: `let
   x: Float64 = 100.0` fails on its own, independent of aliases, so whether the
   fix is a real `Float64` or a spec correction is a decision, not a bug fix.
2. **The universal table is asserted per kind, by repetition.** Each kind's enum
   repeats the same two `static_assert`s. That repetition IS the check — there is
   no way yet to state the table once and have a kind conform to it — so adding a
   kind means copying the block. Worth revisiting if kinds multiply faster than
   expected.

**One interpretation made, worth confirming.** Spec §3 illustrates the typed
handle as `sos_system_shutdown(h: SystemHandle, ...)`, but `sos_system_shutdown`
IS the `@export`ed symbol, and the same paragraph requires exported symbols and
the stubs to keep raw `UInt` words (a C caller sees words; the export whitelist
is primitives). Both cannot hold for one function. The exported C surface was
kept raw and the typed handle put on the `System` METHODS — the Saw-facing
wrapper a Saw process actually calls. The alternative reading, a typed Saw
`sos_system_*` layer beneath the export, would add a fourth altitude to the
three the module documents and explicitly disclaims ("no altitude reimplements
the one below it").

**Gate battery** (each gate's real exit code captured, per the adoption pass's
harness note). Full compiler suite **1373** green (1366 at the branch point plus
7 regression tests for the three gaps); lexdiff zero mismatches over 1530 files
(tokens and docs); astdiff clean over 1530 files; `irdet --all` byte-identical
over 903 examples (38 skipped); blade bootstrap `BOOTSTRAP: ok` (stage0->stage2
plus the lib suites); `make sos-test` 11/11 under QEMU; gmgate 20 programs x 10
runs, 0 failing.

## Design 162 — DF-findings (SOS M1b: arm64 EL1 parity + the HAL extraction)

The headline finding is a negative one and worth stating first: **sawc's
freestanding aarch64 codegen needed nothing.** The Saw half of the kernel
compiled for `aarch64-unknown-none-elf` on the first attempt and every later
failure was in code this branch wrote — assembly, page tables, a manifest. The
port hit ONE compiler-surface sharp edge (DF-162a), and it is not a miscompile.

- **DF-162a — FILED. sawc's freestanding aarch64 profile emits Advanced SIMD,
  and a bare-metal EL1 target traps it out of reset.** `CPACR_EL1.FPEN` is 0
  after reset, so the first compiler-vectorized loop takes an EC=0x07 trap —
  in SOS's case a page-table fill loop in the HAL's C, which faulted BEFORE the
  exception vectors it was being run to install could report anything. The
  generated code is correct for a target with FP enabled; the sharp edge is that
  a freestanding arm64 target does not have FP enabled until its boot code says
  so, and the failure mode is a silent triple-fault-shaped hang rather than a
  link error. Every arm64 freestanding user hits this exactly once, invisibly.
  Three ways out, and picking one is a decision this branch did not take:
  (a) document it in the freestanding profile notes — cheapest, and matches how
  the riscv32 `--target-features +a` requirement is handled;
  (b) make `--target-features -neon,-fp-armv8` work and verify the aarch64
  backend copes with a general-registers-only lowering;
  (c) nothing, since a kernel has to write `_start` anyway.
  SOS took the HAL route — `boot.S` enables FPEN before any compiled code runs —
  and states the consequence in `sos/hal/arm64/kernel/ABI.md`: FP state is NOT
  saved across a trap, which is sound with one user thread and no preemption and
  becomes M2's context-switch problem.

- **DF-162b — FIXED here (unit 1). The "arch-free" kernel was not arch-free.**
  M1's structure note claimed the architecture lived in `sos/hal/`; in fact
  `sos/kernel/core/lib.saw` held an NS16550A register block, a `mcause` enum,
  the PMP wrappers, `mepc + 4`, the SiFive finisher and the board's memory map.
  All of it moved behind a `hal` module. The fix that matters is not the move
  but the ENFORCEMENT: `tools/sos_runner.py` scans the arch-free kernel for
  architecture names, comments included, and fails the run on a hit. A leaked
  constant still COMPILES — it is only wrong on the profile nobody happened to
  be building — so a claim like this one has to be mechanical or it decays.

- **DF-162c — FIXED here (unit 3). `HEX_DIGITS_PER_WORD = 8` made every kernel
  address diagnostic print the low half of a 64-bit word** and look like a
  complete answer. It was written when riscv32 was the only profile. Now
  `hex_digits_per_word()` asks `sizeof<UInt>()`, which is the fact the constant
  was standing in for.

- **DF-162d — FIXED here (unit 3). The sosimg format had no arch tag**, so the
  two profiles' images were byte-compatible headers wrapping incompatible
  instructions and the only thing stopping one booting on the other was that
  nobody had tried. v2 spends the reserved byte on a `SosimgArch` tag; the
  kernel refuses a mismatch before copying anything, Blade writes it from the
  target triple (an unknown triple is a build error, never an untagged image),
  and both profiles have a test that feeds their kernel the other's tag.

- **DF-162e — FIXED here (unit 2). The loader never checked that a segment's
  load address was aligned to the target's grant granularity.** A grant covers
  whole units of it, so a segment starting mid-unit is granted along with
  whatever shares its first unit, at that segment's permissions. On Profile A
  the unit is four bytes and the question never arose; on a page-granular
  profile it is how root's code silently becomes writable because its data
  started 200 bytes later. The check is arch-free (`hal.PROT_GRAIN`) and refuses
  the image.

- **DF-162f — FIXED here (unit 3). Blade's sosimg emitter read ELF32 only**, so
  no 64-bit profile could produce a root image at all. It now takes the class
  from the header and looks its field offsets up (ELF64 widens `e_entry` and
  `e_phoff` and moves `p_flags` ahead of the offsets, so nothing is shared but
  the identification bytes). The 32-bit address fields stay 32-bit ON BOTH
  PROFILES by design — one format, one overlay, one byte count — and an address
  that does not fit is now a REFUSAL naming the 4 GiB bound rather than a
  truncation into an image that loads somewhere the linker never meant.

- **DF-162g — FIXED here. `sos/hal/riscv32/user/ABI.md` documented
  `sos_syscall1_value`, which does not exist** in `syscall.c` and never did. A
  seam document that lists a symbol nobody implemented is worse than a short
  one. The row now says what is true: no M1 op returns a value, and the twin
  belongs beside `sos_syscall1` the day one does.

- **VERIFIED, no gap: the design 148/149 toolkit works on aarch64
  freestanding**, which the brief asked for proof of rather than assumption.
  A `static COUNTERS: SpinLock<Int>` compiles (16 bytes of `.bss`) and lowers to
  inline exclusives with NO `__atomic_*` libcalls left undefined — the opposite
  of rv32i without `+a`, where naming a `SpinLock` is a compile error pointing
  at the flag. Const generics, `[0; N]` and `static_assert(sizeof<Ring<8>>() ==
  64)` all fold at the 64-bit width.

- **CORRECTION to the brief's decision 3.** It notes cortex-a53 as having "LSE
  atomics present". Cortex-A53 is ARMv8.0-A and has no LSE (that is ARMv8.1).
  Nothing was blocked: ARMv8.0 load/store exclusives cover everything the kernel
  and `SpinLock` need, which is what the verification above measured. Worth
  correcting so a later brief does not plan around an extension that is not
  there.

## Design 172 — DF-findings (the SOS C diet)

**The count, over both parts.** Raw lines move with the reason comments the
brief asks for, so CODE lines (non-blank, non-comment) are the honest number:

| file | M1b | after part 1 | after part 2 |
|---|---|---|---|
| `sos/hal/arm64/kernel/sink.c` | 170 | 47 | 47 |
| `sos/hal/riscv32/kernel/sink.c` | 75 | 22 | 22 |
| `sos/hal/arm64/user/syscall.c` | 32 | 32 | **11** |
| `sos/hal/riscv32/user/syscall.c` | 31 | 31 | **11** |
| `sos/rt/common_c/support.c` | 75 | 75 | **44** |
| **total** | **383** | **207** (-46%) | **135** (-65%) |

Part 1 took it out of the two kernel HALs, which is the shape the brief
predicted: the kernel side had arithmetic wearing C's clothes. Part 2 took the
rest — the arena and the four `__saw_rt_*` seams into `sosrt`, and the process
side's two hooks + parked handle into `sos/kernel/sysapi/` — leaving `mem*`,
the atomic libcalls and four inline-asm leaves. Units 1, 2, 3, 4, 6, 7 and 8
landed; unit 5 filed DF-172a. Every surviving line states its reason in its own
file, and sos/spec.md §5c states the three reasons there are.

- **REVIEW ROUND (user, Aug 8): the two kernel HALs no longer each carry the
  write loop or the abort-status rule.** Both had the same twelve lines — poll a
  status register, place a byte, advance a cursor with `&+`/`&-`, count down —
  and the same three-line "mask to a byte, promote zero" promotion. Only the two
  register touches actually differed, and they differ in POLARITY as well as
  shape: a 16550 is ready when LSR bit 5 is SET, a PL011 when FR bit 5 is CLEAR.
  That is a device difference and it is now the only thing a HAL states.

  `sosrt` gained `trait ConsoleSink { can_write, put }` with a default
  `write_byte` (the poll-and-place, since every polled transmitter waits the same
  way), `console_write<S: ConsoleSink>` — the panic path's loop, once — and
  `abort_status(code)`. Each HAL keeps a two-method conformance and its own
  machine-stop mechanism. The bound is STATIC, so the loop monomorphizes per
  architecture with no vtable, no existential and no indirect call on the panic
  path.

  **The DF-172b check-freedom proof was re-run on BOTH monomorphizations, and
  that was the condition for shipping this at all.** Generic-ness could have
  bought a hidden check or an outlined call, so it was measured rather than
  assumed: in each, the generic loop, the trait's DEFAULT body and both accessor
  bodies inline completely, leaving `ptrtoint`, a plain `load i8`, the device's
  volatile load, an `and`, an `icmp`, the volatile store and `add`/`add -1`. No
  `llvm.uadd.with.overflow`, no bounds check, no trap block, no call back into
  `__saw_rt_panic` — 32 IR lines on riscv32, 33 on arm64, both fully inlined.
  `panic_from_check` (the panic-in-panic pin) stays green on both machines.

  Worth recording as a language result, not just an SOS one: a trait with a
  default body, monomorphized through a static bound, cost NOTHING on a path
  whose whole contract is that it cannot trap. That is the property that makes
  `ConsoleSink` the right shape for a HAL seam rather than a nice abstraction to
  be paid for later.

- **DF-172i — a COVERAGE NOTE, not a bug, recorded because it is easy to lose.
  The kernel's `@export`ed typed C surface has no in-tree CALLER any more.**
  `sos_system_debug_print` / `sos_system_shutdown` (sos/kernel/sysapi/) are the
  supported interface for non-Saw processes, and the process-side runtime sinks
  were their only consumer — so when part 2 made those sinks Saw, the last C
  caller went with them. The surface is still specified, still linked (an
  `@export` is anchored by `llvm.used`), and its BODIES still run on every boot
  because the Saw sinks call the same two functions; what no longer happens on
  every boot is a C caller crossing INTO them, which is what
  `sos/root/src/main.saw` and the `root_server_boot` harness case used to claim
  they proved. Both comments now say what is true, and both user ABI.md files
  carry the note.

  Worth a decision when a second process exists: the honest way back is a real
  non-Saw process in the harness, not a C shim kept alive to be called. Adding
  C to the tree to test the C interface is how the diet unwinds itself.

- **DF-172f — FIXED (compiler, isolated commit). An array length that names a
  module `static` was an ICE in TYPE position and a clean error in REPEAT
  position.** `[UInt8; ARENA_BYTES]` reached codegen with an unresolved length
  and died as `internal compiler error: Array type missing element type or
  size`, while `[0; ARENA_BYTES]` said `repeat count is not a compile-time
  constant: `ARENA_BYTES` is not allowed here` with a hint naming the three
  legal forms. One rule, two spellings, and the ICE was the one an author hits
  first, since the annotation is written before the initializer. Design 148
  already named codegen as the position that owns a DECLARED length's
  requirement; it just raised the wrong kind of exception. It now re-runs
  `const_eval` to recover the offending sub-expression and reports a
  `CodegenUserError` with the repeat count's own wording.
  `examples/array_length_nonconst_error.saw` pins it.

- **DF-172g — FIXED (compiler, isolated commit). A static typed through a NAMED
  ARRAY ALIAS ICEd.** `type Region = [UInt8; 65536]` + `static ARENA: Region =
  [0; 65536]` died as `internal compiler error: 'NoneType' object has no
  attribute 'kind'`. `_get_llvm_type` follows an alias, so the LLVM type was
  right, but the STRUCTURAL reads in `_const_from_expr` (`array_element_type`,
  `struct_name`) come off the SawType and are None on an alias node — so the
  array arm recursed with no element type. Resolved once at the top of
  `_const_from_expr` with the existing total `_resolve_type_alias`.

  The spelling is worth having, which is why this was worth fixing rather than
  avoiding: it is how a large region gets ONE declaration of its size — the
  length lives in the alias, `sizeof` reads it back, and an initializer whose
  length disagrees is already a clean type error. The SOS arena uses it. NOT a
  bug, and the test says so: an alias is a DISTINCT type, so it does not
  inherit indexing (`ARENA[0]` is a clean "cannot index into type `Region`")
  and the way in is `(&var ARENA) as UnsafePointer<T>`.
  `examples/static_named_array_type_init.saw` pins it.

- **DF-172h — FIXED (compiler, isolated commit). An `extern` declared
  `-> Never` lowered to an i8 placeholder instead of `void`.** Design 58 says a
  `-> Never` signature is a `void` + `noreturn` symbol, and
  `_declare_function` does that for a DEFINITION; `_declare_extern_function`
  had no such arm and took `_get_llvm_type`'s i8 — the value that exists only
  so an incidental type query does not crash.

  It reached past the declaration, because an `@export`ed definition UNIFIES
  with a pre-existing bodyless declaration of the same symbol and inherits its
  type. So a `-> Never` seam DECLARED in one module and DEFINED in another came
  out as `define noundef i8 @sos_rt_abort(i32)` — exactly the SOS shape, where
  `sosrt` declares the abort hook and each side defines it. Written in an entry
  file with no extern beside it, the same function emitted `void`, which is why
  every design-177 example looked right. Harmless on the targets in tree
  (nothing reads a diverging function's return register; the harness was green
  either way) and wrong everywhere it is written down. The declaration now also
  carries `noreturn`, which it never did.
  `examples/never_extern_module_abi.saw` pins the arrangement; verified by
  reverting the fix (`i8` before, `void` after).

- **DF-172j — LANGUAGE PAIN, filed, NOT blocking. A repeat literal's count and
  an array length cannot name a module `static`,** so a region's size has no
  obvious single spelling. `static ARENA_BYTES: Int = 65536` is refused in both
  `[UInt8; ARENA_BYTES]` and `[0; ARENA_BYTES]` (the first was DF-172f's ICE,
  the second a clean error), and the workaround — writing 65536 twice — is a
  drift the compiler cannot catch on its own.

  The spelling that DOES work, and what this branch adopted, is a named array
  type: the length lives in `type ArenaRegion = [UInt8; 65536]`, `sizeof`
  reads it back for the bound, and the initializer's own length is checked
  against the alias. That is good enough that this is pain rather than a
  blocker. What would remove it is const-evaluating a `static` whose
  initializer is already a literal, which is a language decision (does a
  `static` become a const-expression name, and if so which ones) rather than a
  spelling fix — the same shape as C's `#define SOS_ARENA_BYTES` versus
  `static const`.

- **DF-172a — FILED, and it is the brief's predicted one. Saw cannot name an
  externally-defined symbol's ADDRESS**, so the four `sos_payload_start` /
  `sos_payload_end` accessors stay C. Three shapes were probed and all three
  fail, each for a different reason, which is what makes this a language gap
  rather than a spelling one:

  ```saw
  extern "C" { static _payload_start: UInt8 }   // parse error: "Expected 'func'
                                                //   in extern block"
  extern "C" { func _payload_start() }
  let p = _payload_start                        // error: undefined variable
                                                //   (an extern func is not a value)
  @export("_payload_start")
  static PAYLOAD_START: UInt8 = 0u8             // compiles — and `nm` shows
                                                //   `B _payload_start`: a
                                                //   DEFINITION, which collides
                                                //   with the linker script's
  ```

  The DF-163f-blessed `(&sym) as UnsafePointer<T>` needs a `sym` that is a Saw
  binding; a linker symbol is not one. What the language is missing is an
  `extern` DATA declaration — "this name exists, the linker will place it, its
  address is what I want" — which is `extern char _end[]` in C and
  `extern "C" { static _end: u8 }` in Rust. Two shapes worth weighing when it
  is designed: whether it declares a TYPE at all (the C idiom uses an
  unsized array precisely so nobody reads through it), and whether taking the
  address is the only legal operation.

  There is a NON-language alternative that would delete these four functions
  today, and it is an open question for the user rather than a finding: the
  bounds could be passed INTO `kmain` from `boot.S` (`ldr x0, =_payload_start`),
  which names the symbol in assembly — already bucket 1 — and hands Saw a word.
  It costs every kernel entry a parameter and moves the payload from something
  the HAL is asked for to something the kernel is handed, so it is a seam
  change, not a cleanup.

- **DF-172b — NOT a gap: the panic-path writer is check-free by construction,
  verified from emitted IR.** Design 172 unit 4 says the UART writer STOPS
  rather than ships best-effort if check-freedom cannot be guaranteed. It can.
  `--emit-ir` on the whole call cone (`sos_rt_write` -> `console_byte` ->
  the design-112 driver) shows `ptrtoint`, a plain `load i8`, `add`/`sub` —
  NOT `llvm.uadd.with.overflow`, because the cursor advances with `&+`/`&-` —
  an `icmp`, a `getelementptr inbounds`, and volatile MMIO load/store. There is
  no bounds check, no overflow trap block and no call to `__saw_rt_panic`
  anywhere in it, so a panic raised inside the panic reporter is not merely
  unlikely, it is unreachable. The ingredients that make that true are the
  design-130 raw pointer surface, `&+`/`&-`, and the design-112 `UnsafeMemory`
  driver idiom — no new language work was needed.

- **DF-172e — CLOSED (design 177), and SPENT: part 2 landed on Aug 7.** Saw
  types a diverging loop as `Never`, so unit 2 (the arena + the four seams in
  Saw) went in exactly as the stopped unit had been probed, and the process
  side's hooks — blocked on the same signature — went with it. The predictions
  in the original finding below all held: the arena was expressible,
  `--runtime-provider` permitted and checked the exports, and `sosrt` was the
  module both roles already shared. The second cost it named is paid too —
  `sos_rt_abort` is `-> Never` on both sides now, so
  `__attribute__((noreturn))` is a type rather than a comment. The finding's own
  smallest-first
  suggestion is what landed: a conditionless `while { }` with no `break` types
  `Never`, and `while true { }` is excluded (see the decision entry in the Aug 7
  round). `func spin_forever() -> Never { while { } }` compiles freestanding to
  a `void` + `noreturn` symbol whose body is a bare back-edge —
  `examples/while_never_freestanding.saw` pins the shape. The second cost this
  entry names is paid too: a "this stops the machine" helper (`kcore`'s
  `fatal_image`, `grant_outside_window`) can be declared `-> Never`, which makes
  the guard self-documenting and lets the compiler drop the unreachable tail.
  Nothing else about unit 2 changed, so it resumes where it stopped. **Original
  finding follows.**

- **DF-172e — FILED, and it is what STOPPED unit 2 (the arena). Saw cannot
  type a diverging loop as `Never`**, so a freestanding runtime cannot write
  the `noreturn` panic seam the ABI requires.

  Everything else about unit 2 checks out, and was measured rather than
  assumed. A probe compiled clean under
  `--freestanding --no-hidden-alloc --runtime-provider`, and `nm` showed
  exactly the structure `support.c` has today — the four seams DEFINED, the two
  per-side hooks UNDEFINED:

  ```
  00000000 T __saw_rt_alloc      U sos_rt_abort
  00000000 T __saw_rt_dealloc    U sos_rt_write
  00000000 T __saw_rt_panic
  00000000 T __saw_rt_write
  ```

  The bump arena IS expressible (design 149's `unsafe static var` + a zero
  static + `(&var ARENA) as UnsafePointer<UInt8>`), an `extern "C"`
  declaration in one Saw module unifies with an `@export` definition in
  another, and `sosrt` is already a dependency of both the kernel and every
  process, so it is the module they would share. What fails is one signature:

  ```
  error: `@export` seam `__saw_rt_panic` does not match the runtime ABI:
         it returns `void` where the ABI returns `noreturn`
  ```

  — which is design 149's ABI check doing exactly its job. Meeting it needs a
  `-> Never` body, and the only two things in Saw that produce `Never` are
  `panic()` (which is what this seam IS, so it cannot call it) and an `extern`
  declared `-> Never`. A diverging loop is not one:

  ```saw
  func spin_forever() -> Never { while true { } }
  // error: function `spin_forever` should return `NEVER` but body has no value
  ```

  Profile B could scrape through, because its `sos_platform_exit` is still C
  (semihosting `hlt`) and can be declared `-> Never`. Profile A cannot: after
  unit 4 the finisher write is an ordinary Saw MMIO store and there is no C
  leaf left to lean on. Adding one back to buy a type would be the diet in
  reverse.

  **The decision this branch took: do NOT split the seam family.** Moving three
  of four seams to Saw and leaving `__saw_rt_panic` in C would thread
  `--runtime-provider` through the harness and two manifests, change the
  allocation and panic paths of the kernel and every process image at once, and
  leave `support.c` with a story that is HARDER to state than the one it has.
  `support.c`'s own header already says this move should be taken deliberately
  rather than as part of an adoption sweep, and a language gap in the middle of
  it is the strongest possible argument for that.

  **It costs something ELSE, visible in this branch's own code.** Because no
  Saw function can say "I stop the machine", every diverging helper is typed
  `Void` and the compiler believes control returns from it. So a bounds check
  written as

  ```saw
  if va < RAM_BASE {
      grant_outside_window(va)      // never returns — but the type says Void
  }
  let page = (va - RAM_BASE) >> PAGE_SHIFT
  ```

  reads to the checker as a path where the subtraction runs below `RAM_BASE`
  and traps. It is correct at run time and the harness proves it, but the
  guard's whole point is unstateable, and the same shape is already in
  `kcore`'s `fatal_image`. A `Never` return would make these guards
  self-documenting AND let the compiler drop the unreachable tail.

  What would unblock it, smallest first: an `extern` return type of `Never` is
  already accepted, so the narrow fix is making a loop with no `break` type as
  `Never` — the rule Rust has for `loop {}`. That is a typechecker change to
  the tail-expression rule for an infinite `while`, and it would also let any
  "this function stops the machine" signature say so, which is a thing a kernel
  wants to write more than once.

- **DF-172d — LANGUAGE PAIN, filed. A binary expression cannot be wrapped
  across lines outside brackets — NEITHER spelling works.** Design 129 made
  newlines insignificant inside `()`/`[]`/committed `<>`, but a bare
  continuation is still a statement end, so both of the two things a
  programmer reaches for are parse errors:

  ```saw
  let d = base | DESC_VALID | DESC_PAGE
        | ATTR_AF | ATTR_UXN            // error: Unexpected token: PIPE
  let d = base | DESC_VALID | DESC_PAGE |
          ATTR_AF | ATTR_UXN            // error: Unexpected token: NEWLINE
  ```

  The working spelling is a pair of parentheses around the whole expression,
  which is the shape this branch adopted:

  ```saw
  let d = (base | DESC_VALID | DESC_PAGE
           | ATTR_AF | ATTR_UXN)
  ```

  This is not a corner: OR-ing eight named bits into a hardware descriptor is
  the single most common line in a page-table or register driver, and it does
  not fit in 79 columns. The parenthesis is a workaround a reader has to
  decode as "line continuation" rather than as grouping, and forgetting it
  gives an error that names a token rather than the rule. Worth a decision:
  a trailing binary operator suppressing the newline is the low-risk half
  (the parser has already committed to needing an operand), a leading one
  needs lookahead. Neither is in this brief's scope.

- **DF-172c — the arm64 HAL keeps `CPACR_EL1.FPEN`, and the brief's line about
  dropping it is vacuous as written.** Two facts: the arm64 harness entry
  passed no `--target-features` to begin with (`"features": None`), so there
  were no explicit flags to drop; and `sos/rt/common_c/support.c` — whose
  `memcpy`/`memset` are PERMANENTLY C, being the loop-idiom self-recursion case
  — compiles to 16 SIMD references at `-O2` and is linked into the kernel and
  every process image. Turning FPEN off would trap in `memcpy`. So the boot
  line stays, now with that as its stated reason. Removing it needs
  `-mgeneral-regs-only` on every aarch64 C compile, which means a Blade
  manifest key for per-target C flags (Blade's native compile hardcodes its
  flag list today). Small, additive, and NOT part of this brief.

## Executor — open items

- **EXEC-1 — VERIFY (flagged during the ST lost-wakeup fix, Aug 4, lead).**
  Cross-poller one-shot consumption beyond the fixed case: every poller of the
  process-global reactor (an MT group's workers; a 21b `spawn {}` OS thread
  whose body runs its own cooperative io; the ambient ST sweep) can consume +
  latch a one-shot event belonging to a frame parked by a DIFFERENT poller's
  scheduler. The ST sweep now recovers via its pre-poll latched scan
  (`__saw_exec_any_latched_io`), but only for latches that land while it is
  scanning — a latch that fires while the sweep is already blocked in
  `poll(-1)` (only possible if another OS thread polls concurrently) would
  still wedge it: the event is consumed, the sweep's poll never returns, the
  latch is never read. The MT worker is bounded (50 ms) so it always re-scans;
  the ST sweep is not. NEEDS A PROBE to establish whether the window is
  reachable today (is a concurrent poll possible while the main thread is in
  the ST sweep's poll? MT drains block the main thread; a 21b OS-thread task
  doing reactor io concurrently with main-thread ST io looks like the
  candidate). If reachable: either bound the ST sweep's poll like the MT
  worker's, or self-wake the reactor whenever a poller latches a token it does
  not own. [design 91 / 102 / 118]

## Design 126 — findings (pre-port AST contract)

- **DF-126a — RC-2 is LATENT, not a live bug (measured, Aug 4).** The pre-port
  review called the un-substituted grafted annotations "a live bug, not just a
  port hazard": `substitute_ast_types` walks `dataclasses.fields()`, so while
  `resolved_type` and the ~50 other annotations were grafted at runtime, the
  monomorphizer could not see them, and every `SawType`-valued one was carried
  into an instantiation stale. R1 declares them, so the substituter sees them —
  but the claimed miscompile could not be reproduced. Repro method (kept here
  because it is the way to re-test this cheaply): make the loop at
  `typechecker/effects.py:51` skip `resolved_type` and every field whose
  metadata carries `saw_annotation`, i.e. reproduce exactly what the grafts hid,
  then run the suite. Result: **1034/1034 pass**, including
  `examples/coro_generic_mono_type_subst.saw`, which was written specifically to
  exercise the path (a driven generic-struct method at three instantiations,
  with a `match` over a `T`-parameterized enum and a `Vector<T>` literal live
  across the suspension). So the corpus cannot currently reach a shape where the
  stale annotation changes the emitted code. WANTED: either a shape that does
  distinguish (then it becomes a real regression test), or acceptance that R1's
  value here is contract correctness for the port rather than a bug fix. Do NOT
  describe RC-2 as a fixed miscompile without such a shape.

- **DF-126b — reproducible builds were broken; two causes fixed, no guard yet
  (Aug 4).** Compiling one unchanged source twice produced different IR
  (`examples/hello.saw` differed by thousands of lines). Causes: a `set` of type
  names seeding the codegen topological sort, and a `set` of capture names
  fixing closure environment field order. Both fixed under design 126 R2, and
  `make irdet` now guards a corpus sample. Note the general hazard remains
  unpoliced: any future `set`-of-`str` iteration that reaches emission order
  reintroduces this class silently, because Python randomizes string hashing per
  process and a single run always looks self-consistent.

  **The warning came true — TWO MORE INSTANCES, both in the coroutine transform,
  both FIXED (design 141, Aug 5).** Found by accident, which is the point:
  `tools/irdet.py` samples 40 examples via `random.sample` over the tracked file
  LIST, so simply ADDING two unrelated examples reshuffled the sample and pulled
  in a file that had been non-reproducible all along. Both causes are
  `set`-of-`str` iteration reaching emission order in `coro_transform.py`:
  (a) `promoted` — the set of promoted generic instantiations — was iterated
  into the work list at `transform_program`, which orders `closure`, which
  orders `fbs`, which orders the emitted frame structs and resume methods
  (`examples/coro_nested_generic_deep.saw`); (b) `modes` — the drive modes
  recorded per root by `_effect_record_driven`, a `set` — was iterated when
  emitting the `__saw_drive_*` / `__saw_drive_steps_*` wrappers, at three sites
  (`examples/coro_tuple_across_suspend.saw`). Both now sort. Verified with
  `irdet --all` rather than the 40-file sample.

  **GATE STRENGTHENED (design 146 unit D, Aug 5).** `make irdet` keeps the
  40-file sample as the cheap per-commit check; `make irdet-all` sweeps the
  whole corpus and is now the documented standard for a brief's FINAL gate
  battery (CLAUDE.md's testing section says so). Measured cost of the full
  sweep: **728 examples compiled twice under differing PYTHONHASHSEED, 102
  skipped (they need module paths or a host), 1128.6s of tool time / 18m49s
  wall** on the dev Mac. That is affordable once per brief and not once per
  commit, which is exactly the split. Still open as a cheaper guard: a static
  check for `set`-of-`str` iteration that reaches an emission list — the sweep
  catches instances, not the class.

## Milestones
- **App-1 Blade: DONE** (design 64 + 67; real resolver/lock/git/
  incremental/self-hosting bootstrap; `make blade-bootstrap`).
- **App-2 SOS kernel (ESP32-P4, riscv32): IN PROGRESS.** M0 DONE (design
  112): Saw kernel boots + prints a UART banner + exits cleanly under
  QEMU `virt` riscv32 (`make sos-test`). M1 BUILT (design 140), branch
  PARKED for user review: trap entry + M/U split + PMP, the two-syscall
  ecall ABI (§5.7), the sosimg format with a Blade `emit = "sosimg"`
  target, and `sos/root/` as a real separate package that banners through
  the syscall and exits 0 — 11 QEMU cases. NEXT: M1b arm64 EL1 parity +
  HAL extraction, BEFORE the object model. Ultimate milestone: UART
  "blink" on real P4 hardware. See sos/spec.md §11 + designs/112, /140.
- **Docs website (sawlang.com): VISION (user, Aug 4) — "eventually", not
  scheduled.** A complete site: installation, usage/tutorial, stdlib API
  reference extracted from source. Component (1) doc comments and (2)
  `--emit-docs` are **DONE** (design 121, Aug 4): `///`/`//!` are lexed as
  trivia in both lexers under the lexdiff parity contract, the parser attaches
  them, and `sawc <entry> --emit-docs` writes the typechecked surface as JSON
  (signatures, conformances, suspending-vs-sync effect, self ownership;
  design-80 gate on members). The pipeline is proven end to end on std.task +
  std.time. Remaining component designs to brief when scheduled:
  (3) `sawdoc` — the JSON→HTML generator WRITTEN IN SAW (surface-area strategy:
  markdown/string/file-IO heavy dogfood); (4) the std docstring pass across the
  rest of std (per-module content work, agent-friendly, follow the saw-docs
  skill); (5) site shell + hosting (static; README "Building from a fresh
  clone" section is the near-term precursor). Open questions for (3)/(4):
  Markdown validation and doc-example testing (`sawdoc test`?), and whether
  blade/libs sources join the documented set. [website]

## Queued briefs (Aug 4) — awaiting dispatch

Closed items: see todo_aug1-aug9.md.

- ~~**Design 212 — long-function decomposition sweep**~~ — **LANDED Aug
  12**, units 0-6 (unit 7 skipped per the brief's more-machinery clause),
  tracked battery green. Two findings filed: DF-212a, DF-212b (above).
  Was: (RULED + AUTHORED Aug
  12, dispatched to a Sonnet agent as a mechanical pass). Extraction
  refactor over the Aug-12 review's two hot spots (taskgroup.saw's
  `g[0].<field>` chains, blade) plus a handful of plain duplications and
  one enum-idiom miss; zero behavior change, sos/ out of scope.
  [designs/212-long-function-decomposition.md]
- **PARSER-PORT INTEGRATION STRATEGY (user, Aug 7 — fold into the parser-port
  brief when the rewrite track resumes): a LANGUAGE-NEUTRAL BINARY AST FORMAT
  as the frontend/backend seam.** The format is now DECIDED-BY-BRIEF: design
  169 (Serialize/Deserialize traits + std.cbor, RFC 8949 deterministic
  profile — a standard with an existing Python impl instead of a bespoke
  notation, user Aug 7); the AST envelope (node-id high-water mark etc.)
  layers over it in the parser-port brief. 169 queues post-168 integration,
  before the parser port. The Saw-written lexer+parser emits the
  binary AST per module; the Python typechecker+codegen+LLVM backend consumes
  it — the Saw frontend drives real builds EARLY while the Python parser stays
  the oracle. Cut point is PARSE (the only clean seam: the 164 audit proved the
  parsed AST interchange-safe — 44k objects, ast_dump round-trip byte-identical;
  everything post-typecheck has SawType-aliasing hazards). Staging: (1) format
  spec + Python writer/reader, whole-corpus ast_dump round-trip gate; (2) Saw
  parser emits it, astdiff Saw-parse-vs-Python-parse gate; (3) the flip, Python
  parser kept behind a flag as the permanent battery oracle. Pins: single-source
  the serde on both sides from one schema (design-126 AST contract); the header
  CARRIES the node-id high-water mark and the consumer seeds its counter past it
  (the 164 gate's miscompile lesson); this format is the SEAM, not the Python-
  side perf cache — 168's tier-B pickle stays the Python speed answer; the
  format later doubles as the self-hosted compiler's own AST cache (no pickle
  in Saw).
- **Design 116 — self-hosting pilot: the lexer in Saw (dispatched Aug 4).**
  First permanent stage1 module + rewrite-decision instrument: `selfhost/lexer`
  Blade package mirroring sawc/lexer.py's token model, canonical token-dump
  format, `tools/dump_tokens.py` + `tools/lexdiff.py` differential harness over
  the WHOLE .saw corpus (zero mismatches = bar), LOC/perf metrics, DF-116
  findings as the explicit product. Full rewrite DEFERRED (user, Aug 4) until
  design churn slows; surface-area growth is the chosen mechanism. [116]
- **Design 117 — runtime ABI v2 minimization. LANDED (Aug 4).** Errno
  accessors DELETED; the reactor is INSTANCE-based and relocated to Saw
  (DF-113d dissolved); the thread surface is spawn/join. Per-unit commits:
  thread_spawn/join; instance reactor (rt/host_*/reactor.saw kqueue/epoll,
  compiler `__saw_reactor` singleton getter injected at seam call sites);
  errno→SysError (net, then file/dir/env). Full suite 998 + bootstrap + sos
  green each. `sawc/rt/ABI.md` rewritten as v2 (minimization principle,
  SysError tag table, instance-reactor contract, v1→v2 deprecation table).
  - **DF-117a — DECIDED (user, Aug 7): `if let` block termination matches
    plain `if` (a newline after the closing `}` ends the statement;
    `(if let {...}) - x` needs parens), the NoneType ICE becomes a real
    diagnostic regardless, and the net.saw/os_ops.saw `return 0 - X`
    workarounds revert to the wanted spelling. Queued in the
    soundness/semantics batch. Original finding:** A function whose body is `if let x = y { … }` immediately
    followed by a line beginning with a unary minus, e.g.
    `func f() -> Int { if let p = alloc() { … return r }\n    -SOME_CONST }`,
    parses the trailing `-SOME_CONST` as `(if let {…}) - SOME_CONST` and ICEs
    (`'NoneType' has no attribute 'type'` in operators.py — the if-let value is
    None). A plain `if {}` block does NOT absorb it (the newline terminates),
    so it is an if-let-specific inconsistency in block-expression statement
    termination. Wanted code: `… }\n    -SYS_OTHER` as the fallback value.
    Worked around cleanly with an explicit `return 0 - SYS_OTHER` (net.saw
    net_read_once; os_ops.saw trailing tags). Recorded per the do-not-work-
    around policy: the fix is a parser change to block-terminated-statement
    handling; deferred as out-of-proportion + genuinely ambiguous (blocks are
    expressions, so `block - x` is arguably valid) — flagged for a lead call.
  [117]
- **Design 113 — runtime extraction. IN PROGRESS (Aug 4).**
  - **Physical relocation: LANDED via design 113b (Aug 4).** The `saw_*` export
    reservation was loosened under `--runtime-build` and the seam bodies moved
    to `sawc/rt/` (Saw) + `shim.c` (the DF-113a/b/c bodies) — all seams except
    the IO reactor (DF-113d, see the 113b entry below). See designs/113b-rt-in-
    saw.md. DF-findings stay open as language gaps:
    - **DF-113a — no extern C global.** `__saw_rt_write`/`_panic` need the libc
      `stdout` FILE* (`__stdoutp` macOS / `stdout` Linux) for the `fwrite +
      fflush` that keeps `print` ordered against the still-`printf` Float path.
      Saw has no `extern static` / extern-global syntax, so the body can't be
      Saw. (Switching to `write(2)` would reorder against buffered float text —
      not byte-identical.)
    - **DF-113b — no C function-pointer type.** `__saw_rt_pthread_create` and
      the offload thunk (`word(word)`) pass a raw C function pointer to
      `pthread_create`. Saw's surface has no bare C function-pointer type
      (closures are fat pointers), so threads + offload can't be Saw bodies.
    - **DF-113c — no variadic extern.** `__saw_rt_set_nonblocking` must call
      `fcntl(fd, F_SETFL, ...)`, which is variadic in C (an arm64 ABI
      requirement — a fixed-arity decl reads the flag off the stack). Saw
      extern decls have no `...`, so the reactor's nonblocking-socket path
      can't be a pure-Saw body.
    - **Expressible in Saw today** (for the eventual relocation): alloc/dealloc
      (malloc/free), sleep_ms (usleep), the clocks (clock_gettime + a Saw
      timespec struct), the errno family (extern `__error`/`__errno_location`
      returning `UnsafePointer<Int32>` + `unsafe` deref), sin_set_family (byte
      stores), op-budget + reactor init CAS (`Atomic<Int>.compare_exchange` —
      seq_cst, i.e. stronger ordering than the synthesized monotonic; observably
      equivalent), and the kevent/epoll structs (Saw structs, natural ABI). The
      reactor's `set_nonblocking` dependency (DF-113c) is the only gap in an
      otherwise-Saw reactor.
    - Remaining scope when unblocked: build/cache/link machinery
      (`.build/rt/`, keyed on source hash, auto-linked for hosted builds, `-v`
      shows the objects, clear error if the rt fails to build); delete the IR
      synthesis; the negative test (freestanding still externs, no runtime
      auto-linked — needs a test-harness symbol-inspection directive, which
      doesn't exist yet, and only bites once hosted auto-links); `sawc/rt/`
      module-dir layout selected by target triple. [113]
- **Future designs — language gaps blocking a pure-Saw runtime** (each removes a
  113b shim body or unblocks the reactor when it lands): (1) extern C globals
  (`extern static stdout: ...`) — DF-113a, shrinks shim.c; (2) a bare C
  function-pointer type (closures are fat pointers; thread_spawn/offload thunk
  need thin ones) — DF-113b; (3) variadic extern declarations (fcntl-class arm64
  ABI requirement) — DF-113c. (DF-113d — the array-repeat/uninitialized-local
  poll-buffer gap — is no longer load-bearing: design 117 dissolved it with the
  instance reactor's per-call heap buffer; the language nicety is optional now.)
  General C-interop / low-level value beyond the runtime. [113/113b/117]
- **Design 114 — intrinsic scoping + naming. Part A LANDED (Aug 4); Part B
  LANDED (Aug 4); io_wait gating DEFERRED (see FLAG).**
  - **FLAG — DECIDED (user, Aug 7): io_wait stays UNGATED for now; the real
    gating FOLDS INTO DESIGN 118 (the executor-in-Saw relocation redraws
    this exact seam behind a Reactor trait, and the 11 white-box tests are
    rebuilt against that boundary — deleting reactor-level coverage to
    enforce a gate 118 will redraw would pay twice). No action until 118
    dispatches; its brief inherits this. Original flag:** The brief's Aug-4 audit stated io_wait is "used by std.net"
    (internal only) and budgeted NO io_wait migration. FALSE: **11 example
    programs call `io_wait(...)` directly** — white-box reactor tests that
    drive the FULL raw private seam (`tcp_socketpair`/`tcp_try_read`/
    `tcp_try_write`/`net_buffer`/`net_would_block`/`io_wait`) with controlled
    socketpairs to exercise park/precise-wakeup/cancel/deinit-across-parks at
    the reactor level: `net_io_main_entry`, `net_threads_io`,
    `net_loopback_echo`, `net_socketpair_echo`, `net_io_sleep_interleave`,
    `net_deinit_across_parks`, `net_nested_parks_roundtrip`, `net_io_cancel`,
    `net_precise_wakeup`, `net_precise_n_readers`, `net_three_park_sequence`,
    `net_cancel_parked_mt`. Gating io_wait to std bodies would break all of
    them; there is no public-API equivalent that still tests io_wait itself
    (the public TcpStream examples exercise the seam only indirectly). So
    honoring "io_wait outside std errors" requires a COVERAGE decision the
    brief did not authorize: either DELETE these 11 white-box reactor tests
    (relying on the public-API net tests for regression coverage) or KEEP
    io_wait ungated. Left io_wait exactly as-is (ungated) pending that
    decision; the yield_now gate is independent and complete.

## Design 120 — suspension in expression position (LANDED, Aug 4)

Closed items: see todo_aug1-aug9.md.

- **CARVE-OUT (recorded): multi-hop chained assignment with a suspending RHS.**
  `a?.b?.c = stream.read()` still rejects cleanly; the single-hop
  `a?.c = stream.read()` works. The lowering is a None-guarded
  read-modify-writeback of ONE payload (`var __wp = a!; __wp.c = rhs; a = __wp`);
  more than one hop needs the writeback nested per level. Wanted spelling: the
  multi-hop form lowering the same way. Workaround: `if let` the inner optional
  first. [120, 111]
- **FLAG (minor): a NoCopy payload under a suspending chained assignment
  reports at 0:0.** `var local: NC? = …; local?.x = s(7)` inside a driven
  function is a clean error (`cannot copy value of type ... which implements
  NoCopy`) — the lowering's `local!` read duplicates the payload — but the
  diagnostic carries no source position. The sync form compiles, so the shape is
  legal outside a coroutine. A guard in `_lower_optchain_assign` cannot fix it:
  the transform's typechecker handle has not merged the entry module's namespace
  yet, so `_is_no_copy_type` answers False there. Cosmetic; the program is
  rejected either way. [120, 111]

## Doc-sync audit findings (Aug 3) — two DECIDE items

Closed items: see todo_aug1-aug9.md.

Surfaced by the four-source consistency audit (README / spec / skill /
CLAUDE.md digest vs code); docs were updated to match the implementation,
these two need a design call:
- **DECIDE: method call on an integer literal.** `7.doubled()` is a parse
  error — the lexer consumes `7.` as a float-literal prefix; `(7).doubled()`
  and a bound name work. `Int(7).doubled()` does NOT work (probe Aug 3:
  "struct initialization requires named arguments" — constructor-call syntax
  is structs + distinct aliases only). Decide whether INT `.` IDENT should lex
  as a method call, or whether `(7).method()` is the blessed spelling
  (README's Type Extensions example now uses a binding meanwhile). [57]
  **PUNTED (user, Aug 4):** stays an error for now; `(7).method()` is the
  workaround spelling. Revisit on demand.
- **VERIFY (agent claim, Aug 3): two-suspend helper embedding failure.** The
  design-110 agent reported that a non-driven helper with TWO suspend points
  ("plain `yield_now(); print; yield_now()`, no references") fails to embed
  under a driven body with the nested/expression-position error. NOT reproduced
  by the lead: statement-position `let a = helper()` with two suspends compiles
  AND runs at depth 1 and depth 2 (probes `.build/scratch/probe_two_suspends*.
  saw`, Aug 3). The failing shape, if real, is more specific — extract the
  exact repro from the agent transcript before treating as work. [104, 96]
  **Deferred (user, Aug 4):** revisit only if it reproduces during the SOS
  work (design 112 onward flags suspending-shape oddities on discovery).

## Design 104 — coro embedding: if-let/guard-let bodies + remaining generic shapes (IN PROGRESS)

Closed items: see todo_aug1-aug9.md.

- **Item 2 (cross-module generic driven templates, design-74 shape 4) — ALREADY
  WORKS; regression test added.** The brief's premise (the `_pristine_` capture is
  module-local) is STALE: all modules in one compilation unit are checked by ONE
  shared typechecker (sawc.py's per-module loop in dependency order), so
  `_pristine_generics` / `_pristine_generic_struct_methods` accumulate templates from
  EVERY module (in-tree and `--module-path`). `_splice_fn_mono` /
  `_build_generic_struct_method_mono` therefore find a template regardless of its
  defining module. VERIFIED by probes + the new test `coro_cross_module_generic`
  (module `modules/coro_provider.saw` defines a generic suspending free fn
  `amplify<T: Seed>` + a generic struct `Cell<T: Seed>` with a suspending `charge`;
  entry drives `amplify` NESTED at two types → 211 and `Cell.charge` directly at two
  types → 207/208; IR: distinct `Frame_amplify$1$Lo/$Hi` + `Frame_Cell_charge$1$*`,
  zero plain calls). The stale `_promote_nested_generic_calls` comment ("cross-module
  = shape 4 → reject") corrected. Docs: spec + skill shape-4 now supported.
  **FLAG (discovered, orthogonal — NOT fixed):** a NESTED generic call whose template
  suspends UNCONDITIONALLY without calling a type-param method (`func g<T>(x: T) -> T
  { yield_now(); x }` called nested) fails SAME-MODULE too — the template is not
  `poly_candidate`, so `_process_effect_monos` never builds its instantiation's
  suspend node, so `_promote_nested_generic_calls` can't promote it and it lowers as
  a plain call → a clean (not silent) sync-violation error on the synthesized resume.
  Precise blocker: build a generic instantiation's effect node when the TEMPLATE
  structurally suspends (a direct `__suspend`/`yield_now`/`sleep`, not gated on a
  type-param method), not only when `poly_candidate`. Workaround: drive it directly
  (`__drive`/`spawn`), or give the template a type-param method call. Suite 941 (+1),
  bootstrap 17+17 + libs 4+4. [104, 74, 70, 96]

## Design 89-b — executor unification core (WORKTREE, IN PROGRESS)

Closed items: see todo_aug1-aug9.md.

- **Test matrix — LANDED (worktree).** Three NEW tests for behavior the old split
  executors could not produce (suite 888->891): `net_accept_loop_concurrent`
  (ACCEPTANCE — a server task accept-loops N=3, SPAWNING a handler per connection
  into its OWN group that runs eagerly on the shared scheduler while the server
  parks, + 3 concurrent client tasks; round-trips all N, deterministic 3/3);
  `taskgroup_spawn_and_loop` (the core gap — main parks in a sleep-loop while its
  spawned child INTERLEAVES `0,100,101,1,102,2,7`, not the old
  `0,1,2,100,101,102,7`); `taskgroup_nested_ambient` (nested groups + a task
  joining its own inner children = the reentrancy hazard, cross-group eager
  interleave). Existing coverage survives and validates the rest under the ambient
  scheduler: `taskgroup_sleep_ordering`/`structured_join`/`unjoined_drop`/
  `two_task_yield`/`cancel_check`, `net_io_sleep_interleave`, `net_serve_two/three_
  connections`. Updated the now-stale per-group-executor comments in
  `taskgroup_nested_groups` + `taskgroup_suspending_parent_sleep` (results kept).
  **DF finding (pre-existing, reproduces on parent):** spawning a function whose
  param transitively references a std struct (e.g. `f(h: TaskHandle<Int>)`) ICEs
  "Undefined struct: TaskGroup" during frame layout — unrelated to executor
  unification; reentrancy is instead tested via nested-group joins. [89, 52b, 76]

## Decisions needed (user input required)
- **D10.** Cortex-M0-class atomics (ARMv6-M has no CAS) — decide with
  the first such port. [19, 20]
- **SOS**: design session Aug 3 ratified spec §7–§10 — scheduling
  (8 levels, band enum + immutable manifest-declared launcher-approved
  map, LAUNCH capability, no inheritance, direct-switch, UP v1),
  thread/process lifecycle (fault→process-exit, no join/thread-kill,
  Thread+Process handles waitable, get_status/kill rights-gated),
  interrupt delivery (mask-on-fire/ack-to-rearm, ack-is-release,
  one-task-per-IRQ v1, `wait(ack:)` combined form), and the userspace
  runtime model (TaskGroup unchanged; NEW `HandlerGroup` = handles on
  a task pool, move-in/coat-check API, per-attachment non-reentrancy,
  borrow-per-invocation, wake-word key bridge). REMAINING before the
  kernel briefs (spec §11): ONE user design session — root server
  responsibilities + v1 userspace protocol; then the veto-able
  orchestrator pins (rights bits/op tables, memory layout, refcount
  placement, sosimg constants incl. priority-map field) land inside
  the M1/M1b briefs (numbers assigned at dispatch; the spec's old
  78/79 references are stale).

- **DF4 (meta).** Blade bit-rots as the compiler tightens — re-validate
  periodically (the bootstrap target is the canary). [49]
- **DF5.** Keywords (`extension` etc.) can't be identifiers — fine, but
  an eventual contextual-keyword sweep is noted. [49]
- ~~**DF6 (latent coro-transform bug, found in the post-92 net idiom
  skim, Aug 2).**~~ CLOSED (design 96). Root cause was NOT the
  infinite-loop shape but a `break`/`continue` inside a NON-spanning
  `if`/`match` nested in a suspension-spanning loop: `_lower_inplace`
  kept the raw jump, which breaks the resume method's `while true`
  DISPATCH loop instead of the logical loop → re-entry hangs. net
  read()'s break form triggered it via its `else if …else {break}`
  (a non-spanning inner if in the else of the spanning io_wait if).
  Fix: `_has_loop_ctrl` forces a CFG split of such an if/match when in
  a spanning loop, routing the jump to the loop state via `loop_ctx`.
  read() converted to the break form, NOTE removed; regression
  `coro_break_reentered_in_loop`.
- **B4 limit.** A git dep's locked REV isn't pinned without
  re-resolution (build-from-lock path reconstruction is future work);
  path deps unaffected. [64, 67]
- ~~**L18 — module-qualified type annotations (found in design 68).**~~
  FIXED (design 69). The typechecker resolved a dotted annotation
  (`v: mod.Type` / `let x: mod.Type` / `-> mod.Type`) for checking but
  left the dotted `struct_name` on the AST, so codegen ICE'd "Undefined
  struct: mod.Type". Fix at the source: write the resolved (qualifier-
  stripped) type back onto the AST — free-function params (registration),
  let annotations + method params/return (a guarded `_resolve_type` when
  `_annotation_has_module_qualifier` holds, so generic/Self are untouched).
  A related typechecker gap fell out (a method with a qualified param
  errored "body has no value" because the param scope kept the dotted
  type) — fixed by the same write-back. Locked by
  `examples/l18_module_qualified_annotation.saw`. [68, 69]
- **L2.** Return-type reconciliation for type-param/associated-type
  returns in generic bodies — documented deferred looseness. [02, 24]
- ~~**L9.** `==` over Optional-/array-bearing members: deliberate clean
  error; extend the equals derivation when needed.~~ CLOSED (landed e60d189;
  enum-Optional-payload case closed under design 72): the Equatable synthesis
  lowers `T?` (None/Some-aware) and `[T; N]` (element-wise) members. [32, 72]
- ~~**L12.** Fixed arrays can't take extension methods (parse error);
  also blocks fixed-array `.len()` (spec-illustrative).~~ CLOSED (design 72):
  fixed arrays get builtin `.len()` + `.swap(i, j)` (M1 escape hatch); user
  extensions on array types stay rejected with a clear diagnostic. [40, 72]

## Deferred features (decided or triaged, not scheduled)
- ~~Erased-error DOWNCASTING (needs a type-id design; catch-all boxes are
  opaque until then).~~ CLOSED (design 72): vtable `type_id` slot + `Box<any
  Trait>.is<T>()`/`take<T>()`. Catch-side match-on-concrete sugar still deferred
  (future). [56, 72]
- Debug trait (synthesized structural formatting) — own design. [56]
- Enum-direct Printable (enum method dispatch is a general gap). [56]
- Named tuple PATTERN form `(x: a, y: b)`. [63]
- Map `entries()` snapshot; Map ExplicitCopy/.copy(). [54, 57]
- Labeled-arg `_` opt-out; labeled-only enforcement. [66]
- Integer range-cover exhaustiveness. [63]
- Generic-method type-arg inference. [36]
- ~~Closure-Deinit: wire `codegen_env_dtor` into closure drop glue (C4).~~
  **CLOSED (design 71 landed):** escaping closures carry their env destructor
  and drop it at the closure's own drop (exactly once); early frame release
  removed; escaping closures are NoCopy. Residual owning-closure-in-copyable-
  struct-then-copied gap tracked under the design-71 section. [21b, 59, 71]
- `Weak<T>` (Arc slot reserved). [16, 21]
- Slices (needs own design vs no-escape refs); `\x` byte escapes;
  where clauses; extension sugar (computed properties, conditional
  extensions); submodule directories; std.io traits (Blade-driven).
  [user triage Jul 29]
- S5 small-string optimization — ABI-gated ("before separate
  compilation or never"). [07]
- Registry for Blade (salvaged sketch, old pm design): static HTTP
  index or git repo; `GET /api/v1/crates/{name}` metadata +
  `/{version}/download` tarball; `blade login/publish`. [pm_design,
  deleted Jul 30 — see git history]

## Async (post-52b roadmap)
- ~~**A5.** Effect polymorphism via monomorphization-time re-inference —
  BLOCKS generic suspending/driven functions.~~ DONE (design 70): effect
  inference runs PER instantiation (keyed by mangled symbol); the coroutine
  transform accepts suspending instantiations of generic functions/methods by
  monomorphizing them to concrete functions/methods before frame synthesis
  (driven free fn, `TaskGroup.spawn`, and `&var self` method all land). A `sync`
  context calling an instantiation that suspends is a violation reported AT the
  call, naming the instantiation + suspension path (minimal A8). Still rejected
  with precise diagnostics: a buried suspending method-on-`T` call inside a
  driven body, nested suspending generic calls, generic-struct-extension driven
  methods, and cross-module generic templates (re-ledgered below). [18, 22]
  - **A5-rest.** PARTLY DONE (design 74): driven methods on GENERIC structs
    (shape 2) and nested suspending generic calls (shape 3) LANDED; A8 diagnostic
    anchors LANDED (coroutine-transform rejections anchor at the user's
    file:line:col). Remaining, now CLEAN user-anchored rejections (re-ledgered
    under the design-74 section with analysis): buried suspending METHOD-call
    embedding (shape 1, the Part-0b method twin); cross-module generic driven
    templates (shape 4, design 68 territory). [70, 74]
- ~~**A2.** Multi-threaded work-stealing executor + Send-on-frames check.~~ DONE
  (design 75): `TaskGroup(threads: N)` runs N OS workers over a single
  mutex-protected shared queue (fork-join drain; per-worker lock-free deques
  deferred as documented — the sanctioned simpler shape). Send-on-frames gate on
  spawn into a multi-threaded group (params + across-suspend locals + result). D6
  confinement preserved (one worker per frame; frames move only between
  suspensions). Cross-task cancel via `TaskHandle.cancel_addr()`. [18, 52b, 75]
- **A3.** Explicit-only cancellation points (`Task.cancelled()`, select).
  MOSTLY DONE (design 76): cancellation observed at the io suspension point via the
  cancel-check-before-`io_wait` idiom (+ the existing channel/yield checks).
  Remainder: waking an ALREADY-io-parked task on cancel (self-pipe) — re-ledgered
  under design 76.
- ~~**A4.** IO reactor (poller-only v1, kqueue/epoll, never-block).~~ MOSTLY DONE
  (design 76): global kqueue/epoll reactor + `io_wait` intrinsic + std.net
  nonblocking TCP; ST group + entry executor never-block poll. Remainders
  re-ledgered under design 76 (MT integration, first-class inline-lowered
  read/accept/write). [18, 76]
- ~~**A6.** `extern blocking` offload pool.~~ DONE (design 76 front-end + the two
  type-system rejections; design 103 the runtime offload + coro lowering — a
  blocking call inside a suspending body now RUNS on a worker thread and parks on
  its pipe; see the design 103 entry). **A7.**
  Separate-compilation interface format w/ suspends bit. ~~**A8.** Suspension-path
  diagnostic anchors.~~ DONE (design 74): coroutine-transform rejections + sync
  violations anchor at the user's file:line:col with a source snippet, naming the
  instantiation + suspension path. ~~**A9.** Actor sugar.~~ DROPPED from the
  roadmap (user, Jul 31). [18, 74, 76]
- Two runtimes coexist (thread-engine spawn/Task vs cooperative
  TaskGroup) — unification unscheduled. [21b, 52b]

## App-2 / freestanding path
- ~~**F7** remainder: assembly boot shim + wiring. **F8** linker scripts.
  **F9** QEMU riscv32 smoke ("blink") + CI.~~ DONE (design 112, Aug 4):
  `sos/kernel/` boot.S + virt.ld + rt.c runtime seams + `main.saw` (UART
  driver over `UnsafeMemory<_, Device>`); boots under `qemu-system-riscv32
  -M virt -bios none`, prints a banner, exits 0 via `sifive_test`; trap
  stub + freestanding panic seam both FAIL the run (never hang);
  `make sos-test` (tools/sos_runner.py) + ubuntu CI job. **F10** fence/
  barrier primitives for DMA ordering. [20, 46, 58, 112]
- ISR conventions; riscv32 target completion (i32 word landed, 47).
- **DF-112a (design-112 discovery, FIXED in this brief — sawc touch, flag
  for the lead vs concurrent design 113):** two freestanding-riscv32
  blockers surfaced on first bare-metal use. (1) An ICE — `_generate_spawn`
  (codegen/calls.py) hardcoded `i64` for the `saw_alloc` seam args instead
  of `self.int_type`, so ANY freestanding riscv32 compile ICE'd ("i32 !=
  i64") because codegen emits every loaded stdlib method incl. a spawn-using
  one (last un-migrated design-47 site; closures were already migrated).
  Fixed to platform-width. (2) Dead-code strip — codegen emits every loaded
  stdlib method + its closure/vtable descriptors + backend constant pools
  regardless of reachability, and freestanding still loads channel/mutex/
  task/float-print methods referencing pthread/snprintf/float/atomic
  symbols a bare-metal target can't satisfy. Added a freestanding-only
  post-pass (`_apply_freestanding_sections`) that internalizes non-`@export`
  defs (so O1 `globaldce` deletes everything unreachable from `kmain` +
  `@llvm.used` — the primary mechanism, reaches fused constant pools that
  IR-level sections cannot) + per-symbol sections for `--gc-sections`.
  Host suite 993/993 green (freestanding-guarded, hosted byte-identical).
- **DF-112b (pin deviation, design 112):** the pinned ISA was
  `rv32imac_zicsr`, but llvmlite emits `rv32i` (base, ilp32 soft-float)
  for the `riscv32-unknown-none-elf` triple — sawc exposes no CLI feature
  string to request imac. rv32i runs fine on QEMU's default `virt` rv32
  CPU (a subset); boot.S/rt.c are assembled `rv32imac_zicsr` and link
  cleanly. If a kernel needs mul/div/atomics inline (not libcalls), sawc
  needs a `--target-features` surface — future work, not M0-blocking.
- **DF-118a (design-118 stage-3 discovery, FIXED in that brief — sawc touch):**
  the IO reactor seams (`__saw_rt_reactor_create/register/poll/wake/destroy`) were
  declared with a hardcoded `i64` in `codegen/core.py::_declare_io_runtime`, but
  they carry `Int` (platform word). Latent since design 117 — freestanding never
  referenced a reactor seam (the compiler-synthesized `__saw_reactor()` getter was
  `internal` + unreachable → stripped before the width mattered). Design 118 stage 3
  moved the reactor singleton into the prelude std (`__saw_host_reactor()` /
  `SystemReactor` in taskgroup.saw), so the seams are now CALLED from Saw and their
  IR is generated on the freestanding riscv32 target too — where `Int` is i32,
  producing an invalid `cmpxchg i32 … i64` against the `Atomic<Int>` cell (IR
  parse error). Fixed to `self.int_type` (platform word) — byte-identical on the
  64-bit hosted targets, correct i32 on riscv32 (same class as DF-112a). The
  sos_runner (freestanding riscv32 QEMU) is the regression test.
- **F5.** `Once`/`Lazy<T>`, `PerCpu<T>`, UnsafeCell-equivalent story.
- **F6.** dtoa/Float printing under freestanding. [20]
- ~~**T1f.** Debug info (line tables → backtraces).~~ DONE (design 69):
  DWARF line tables on by default; lldb breakpoints + `file:line`
  backtraces; panics/asserts name their source location. [tier-1]
- `AllocatedBy<Slab>` sugar. [19, 42]

## Testing & infra
- **M2.** Unit tests for lexer/parser/typechecker internals; fuzz/
  differential testing; property tests over copy/move rules. [critique]
- ~~CI: GitHub Actions workflow for suite + bootstrap.~~ DONE (design 69):
  `.github/workflows/ci.yml` (ubuntu + macos) runs the compiler suite,
  the debug-info test, the blade bootstrap, and semver/toml lib tests;
  README badge. Linux is a new target — first CI run may surface small
  follow-ups (PIC-reloc + sys.executable portability fixes landed).
- ~~Runtime error messages with source locations (subsumed by T1f).~~
  DONE (design 69): panics carry `FILE:LINE`.

## Research tier (post-both-apps)
Const generics; const fn; macros; compile-time reflection (PMP
generation consumer, 46); Char/Int128/Float32; `**`/`::` operators;
Deque; RwLock/Barrier; std.net (after A4); async select;
Sender/Receiver split; §11 futures (effect system, dependent/linear/
refinement types, first-class modules); REPL/LSP/formatter; `defer`/
`do` reserved-word decisions.
