# Design 247 — The DF-215f Fix: Retire the Legacy Scrutinee-Temp Encoding

**Status: AUTHORED + DISPATCHED Aug 27 2026** (lead, from the obligation-4
sweep's report, same day; the user's Aug-27 "launch DF-215f" covers the
pipeline sweep -> brief -> fix). **Queue: HEAD** (user Aug 26: a correctness
bug outranks everything scheduled). Agent DF range: **DF-263a+**.

## What the sweep established (Aug 27; 30+ probes, all compiled AND run)

**DF-215f is a class, and its filed entry UNDER-states it.** One mechanism —
the transform's hoisted scrutinee temp keeps ownership of an enum/optional
payload while the arm's payload binding is a codegen-level alias, so a `move`
out of that binding creates a second owner and nothing disarms the temp —
produces a DOUBLE RELEASE in EVERY driven `match`/`if let` over a suspending
scrutinee whose arm moves the payload out. **The filed third leg ("the moved
value crossing the function return") is FALSIFIED**: move-out to an outer
local, straight into a consuming call, into a Vector, and the pin's own
`local_use` row (which asserts Clean) all double-release. Return-crossing only
buys observability — with a refcounted payload the extra release lands while
another owner is live (use-after-free, SIGSEGV); without it, it lands after
the last legitimate release and silently underflows — which is why the pin's
Arc-instrumented idiom mis-graded `local_use` as clean. Probes detecting the
second release used a NoCopy payload with a hand-written printing `deinit`.

### The mechanism, precisely (sweep §1, IR-verified at -O0)

- `_scrutinee_temp_release` (`sawc/coro_transform.py:5797`, edge "E-STMT/2c",
  called from `_split_match` ~6422 and `_split_if_let` ~6175) emits an
  idempotent tag-drop of the `__matchN`/`__hoistN` frame temp at the merge
  point. Its stated invariant — "an arm whose binding CONSUMED the payload
  already cleared the tag through the DF-210f forget" — only holds when the
  payload binding is FRAME-RESIDENT: the forget is gated on
  `bname in self.encmap` (`_split_match:6358-6381`; the identical gate in
  `_optbind_dispatch:6123-6133`). A non-suspension-spanning arm's binding is
  never frame-resident (DF-218s residue (a), recorded), so no forget runs and
  the temp still owns the payload at the merge.
- Codegen covers nothing either: `codegen/match.py:170`'s `scrut_is_local` and
  `_is_owned_temporary` both read the SYNTAX of the scrutinee, and a frame
  field access is neither — `consume_name` stays None, no arm cleanup scope is
  pushed, no binding gets a drop flag (`match.py:315-362` all skipped). Right
  for a non-moving arm (the binding is a read-only alias); wrong the instant
  the arm writes `move <binding>` — the move is bookkeeping-invisible on BOTH
  sides of the seam at once.
- The sync twin is correct because codegen spills the scrutinee itself
  (`match.py:187-199`, DF-151d), sets `consume_name`, suppresses the
  scrutinee's own drop, registers owning bindings into an arm cleanup scope,
  and a `move` clears the binding's drop flag. One owner throughout.

### The boundary — five conditions, each with a removing probe

A wrong release needs ALL of: (1) driven body; (2) the subject is a
LEGACY-ENCODED hoist temp — `__matchN` (`_maybe_hoist_match`) or `__hoistN`
(`_hoist_cond`); (3) owning payload; (4) the arm binds the payload by name AND
does not span a suspension (so the DF-210f forget never runs); (5) the arm
hands the value onward — any `move` out, to ANY destination. NOT on the list:
return-crossing.

Clean by construction, probed: sync twin; non-moving arms; arm-suspends
(residency forces the forget); `guard let` / `while let` (bindings
frame-resident unconditionally); every design-218-stage-2 MIGRATED family —
ANF argument/`??`-RHS/interpolation temps (`__anfN`), `try`/`try!`/`try?`
operands (`__trycallN`), tuple destructuring, `Optional.take`, TaskGroup and
`Task.spawn` joins, and the container-head hoist at the Copy tier (`__headN`)
— all clean because their temps are read with `take()`
(`coro_transform.py:6177 _takes_temp`): ownership physically leaves the slot
at the read, no claim survives. The affected cells are exactly the two
families stage 2 did NOT migrate (`FAM_SCRUTINEE_TEMP`, design-44 legacy
encoding, `coro_transform.py:841`; the `_optbind_dispatch` docstring already
says the legacy rule "goes with the last of them").

Neighbours: **DF-218w residue** is the SAME temp on the SAME edge one
arm-shape over (E-ARM early-releases on an all-`_` arm; condition 4 is its
exact complement) — this fix is expected to SUBSUME it. **DF-242a** (codegen-
owned error edge, timing divergence, no double free) and **DF-255a**
(escaping-closure capture env — same shape, different pass, reproduces with
no coroutine) are NOT subsumed and stay open.

## The fix (ruled by dispatch): finish the design-218-stage-2 migration

Migrate `FAM_SCRUTINEE_TEMP` — both `__matchN` and `__hoistN` — to the
`take()`-read encoding the nine clean families already use, and delete the
legacy E-STMT/2c edge (`_scrutinee_temp_release`) and the DF-210f forget
machinery WITH the last legacy family, per the `_optbind_dispatch` docstring's
own closing sentence. This targets the mechanism, not the symptom: after the
read, the temp slot is empty, the scrutinee is an owned local, and codegen's
existing consume model (`consume_name`, arm cleanup scopes, drop flags — the
sync path that is already correct) applies. The agent verifies that the
migrated scrutinee actually engages that model (or whatever equivalent the
nine migrated families rely on — match the family that is already right, do
not invent a third discipline) — the sweep's second observation is that
`scrut_is_local`/`_is_owned_temporary` judge syntax, so confirm what the
take-read form presents to them and that arm bindings get real drop flags.

Expected consequences the landing MUST handle:
- The 215f pin (`examples/coro_match_moved_payload_survives_return.saw`)
  flips: remove the XFAIL marker in the same landing, AND CORRECT ITS MATRIX —
  the `local_use` row asserts Clean and is actually a double release; the
  row's expectations must state the fixed behavior with a NoCopy printing
  deinit, not the Arc idiom that hid the underflow.
- The DF-218w residue pin (mixed `case Both(v, _)` statement-end timing) is
  expected to flip XPASS: remove its marker in the same landing and close its
  tracker entry; if it does NOT flip, explain why in the report (the two
  cells are complements on the same edge — a fix that flips one but not the
  other has misunderstood the edge).
- `tools/corodiff` known-ledger: check `corodiff_known.txt` (and
  `sawfuzz_known.txt`) for entries this fix closes — the SAME commit that
  fixes removes the ledger entry, and the gate includes that harness's lane.
- Release ORDER/timing changes at the merge point are behavioral (obligation
  2): the consumer sweep is the DF-215f sweep itself plus the suite — the
  sweep's B-matrix (16 clean constructs) is the do-not-break contract, and
  the corodiff/irdet/reemit lanes police the corpus. The known in-tree
  consumer of the OLD timing is the DF-218w residue pin (expected flip,
  handled above).

## Units

**Unit 0 (obligation 3, FIRST): the conformance row.** The broken guarantee
is "an owned value deinitializes exactly once" under driven match/if-let
move-out. Check `examples/conformance/INDEX.md` for the owning row; add or
update it to cite the covering test (the corrected 215f pin or a dedicated
conformance test), before the fix lands.

**Unit 1: the migration** + the full regression matrix. Every AFFECTED sweep
row becomes an `examples/` test named for its behavior (NoCopy printing-deinit
idiom; EXPECT the single-release output): match move-out crossing return
(the pin), to an outer local, into a consuming call, into a Vector, `let`-
initializer match with local use, `if let` move-out (both destinations), user
enum scrutinee (not Result/Optional), match-in-loop (once per iteration),
match inside `try{}catch{}`, match inside a spawned task. Controls: the sync
twin, the non-moving arm, the arm-that-suspends. The nine migrated families'
clean rows are covered by existing design-218 tests — VERIFY that before
skipping any; add the row if a family has no existing move-out test. Rebuild
probes from the brief's boundary description where scratch files are gone.

**Unit 2: repay the llm_client debt.** `llm_client.saw` carries `try!` in
place of `match` on every suspending TcpStream op, with comments citing
DF-215f (the tracker's design-215 entry records this as DEBT this fix
repays). Restore the designed match-based error paths (the connect-failure
path exits via the designed ClientError line, not a panic) and delete the
workaround comments. Verify against the loopback mock only if cheap; the
compile + the suite are the gate otherwise.

## Gates

Compiler branch: per-commit full suite + `tools/freestanding_runner.py` (both
arches) through the machine-wide suite lock; terminal full battery
(`tools/battery.sh`) — the `corodiff` lane is the one this change most owes,
plus reemit/irdet for the emission-order consequences.

## Obligations ledger

1. The take-read encoding IS the funnel (one read discipline for every hoist
   family; the legacy edge is deleted, not patched). 2. Consumer sweep = the
   Aug-27 sweep's B-matrix + the DF-218w flip handling above. 3. Unit 0.
   4. The sweep (this brief's whole basis).

## Appendix — incidental findings filed by the sweep (OUT of 247's scope)

**DF-262a (diagnostic):** the container-head hoist's move-only refusal names
the compiler-internal frame field to the user:
``error: `self.__head0.value(…)` lends a place of type `Result<Res, MyErr>`,
which is move-only …`` — fires on `match get_maker("h0").build() { … }` at a
move-only tier, and on `if let r = try? suspending()` at `Res?`. The refusal
itself is correct (it is what fences the head-hoist cell off from the 215f
family); the SPELLING leaks `self.__head0`. Diagnostic-only.

**DF-262b (ICE):** three ingredients in one driven body, ALL required
(removing any one compiles): a suspending call in an interpolation piece
(design-120 ANF temp), a `Task.spawn` of a suspending call at the SAME NoCopy
result type, and the joined value landing in an optional slot (auto-wrap).
`internal compiler error: LLVM IR parsing error — ret {i1, %"Res"}
%"autowrap_val" … doesn't match function result type '%Res = type { ptr }'`.
Repro (preserved verbatim from the sweep's minimal probe):

```saw
import std.task.{yield_now}

struct Res { name: String }
extension Res: NoCopy {
    func deinit(&var self) { print("DEINIT {self.name}") }
}
extension Res: Printable {
    func format(&self, into: &var StringBuilder) { try! into.append(self.name) }
}

func make_res(name: String) -> Res {
    yield_now()
    return Res(name: name)
}

func main() {
    print("interp {make_res("n1")}")
    var slot: Res? = None
    let t = Task.spawn(make_res("n2"))
    slot = t.join()
}
```
