# Design 261 U1 — the obligation-2 consumer sweep

Obligation 2 ("a behavioral-contract flip owes a consumer sweep") names this
brief as its own canonical example: by-value -> by-pointer. Brief §3 U1 names
four targets (a)-(d). Two read-only sweeps ran before the flip — one over the
2,707 tracked `.saw` files, one over `sawc/` Python — both backed by direct
compile/run evidence rather than grep alone. This is the record.

## Ground truth: the receiver ABI before the flip

Straight out of the emitted IR, one probe per shape:

| receiver | LLVM parameter 0, before |
|---|---|
| plain `&self`, aggregate | `%Group %self` (by value) |
| `&var self` | `%Group* noalias %self` |
| cell-carrying `&self` (design 186) | `%Celled* %self` (pointer, no attributes) |
| `borrows &self` (design 146) | `%Grid* %self` (pointer, no attributes) |
| `Vector.len(&self)` | a 4-word struct, by value |

Address identity, measured:

```
caller == (&var self)-derived address : true
caller == (&self)-derived address     : false
&var self.n  == caller's field        : true
&self.n      == caller's field        : false
[&self] capture == caller's storage   : false
write through a (&self)-derived pointer, observed by the caller : discarded
```

## (a) Unsafe code deriving pointers from a `&self` receiver

**Result: zero AT RISK consumers.** Every address-derivation in the corpus
already uses a receiver that is by-pointer TODAY.

- `&var self` — 6 sites in `sawc/std/taskgroup.saw` (`__start_crew`,
  `__register`, `__bt_link`, `__bt_unlink`, `__unregister`, `deinit`, all
  `(&self) as UnsafePointer<TaskGroup> as Int`), plus `sawc/std/fixedbuf.saw`'s
  `ptr(&var self)` — which is the gotcha's own worked example, declared `&var
  self` precisely to get a real address.
- cell-carrying `&self` — ~14 sites (`spinlock._payload`, `mutex`, `once`, and
  the `examples/interior_cell_*` pins). By pointer since design 186.
- `borrows` accessors — ~30 sites. By pointer since design 146.
- Reading a STORED pointer field (`Data`, `String`, `channel`, `arc`, `alloc`,
  `process`) is identical under either convention — the field's VALUE is the
  same either way. Unaffected, as the brief anticipated.
- `sawc/rt/` declares no `&self` methods at all.

**Sites that IMPROVE** (they addressed the callee's copy and now address the
caller's storage; all read-only, so no output changes):
`examples/closure_captures_self.saw`'s `body(&self.n)`,
`examples/conformance/R39_*`'s `[&self]` captures including a suspending one,
`selfhost/lexer`'s nine `ubyte(&self.src, ...)` calls,
`blade/src/builder.saw`'s two `&self.layout` forwards, and
`sawc/std/data.saw`'s `String.fromBytes(&self)`.

**The escape hazard the flip could have created is already fenced.** An
escaping closure capturing `self` is refused in both the implicit and the
explicit `[&self]` spelling, and the existing diagnostic already describes the
POST-flip ABI: "a method's receiver is a borrow of storage the CALLER owns".

## (b) The mono/codegen internals' receiver assumptions

The brief's claim was that `calls.py`'s by-construction coupling keeps
monomorphization in step. **The claim holds, and the declaration side is
cleaner than claimed** — but the sweep found the real hazard one layer over,
on the CONSUMER side.

DECLARATION: exactly one site builds an instance method's signature
(`core.py`'s instance arm, reading `_self_by_pointer_for`) and exactly one
binds the body's `self` (`methods.py`). Monomorphized methods, trait default
bodies and the derived `copy`/`equals`/`compare`/`hash` all reach those two by
AST splicing — they have no independent declaration path. Vtable slots and the
erased dispatch thunk take an `i8*` receiver by design, independent of the
convention. `deinit` is `&var self` by construction. `@export`/`--runtime-build`
apply to free functions and statics only, so no method path exists there.

CONSUMERS: `calls.py` infers `is_mutable_self` from `method_func.args[0].type`,
`_forward_self_arg` reads `function_type.args[0]`, and the vtable thunk reads
`impl.args[0].type` — all three read the EMITTED SIGNATURE and are in step by
construction, exactly as claimed. But **ten compiler-synthesized call sites
passed `self` as a loaded VALUE with no reference to the callee's signature at
all**, correct only because a by-value aggregate receiver was the only thing
that had ever existed: struct and String `equals`/`compare`/`hash`, the
retain-in-place leaf copy, `_generate_copy`, the element deep copy, a derived
`copy()` body's per-field copy, the `.hash(&h)` intercept, the drop glue's
`deinit` call, and `Iterator.next` in a `for` (which passed a pointer
unconditionally and would already miscompile a `&self` `next`).

That is the DF-216a mechanism — a compiler-synthesized call construction is the
family that skips whatever the ordinary call path does — so the fix targeted
the mechanism: `_self_operand(fn, receiver)` reads parameter 0 and adapts, with
its entry points named in its docstring per obligation 1. Landed ahead of the
flip as a no-op refactor (U1a).

**DF-293a, found by this sweep and fixed in U1b.** The by-pointer receiver arms
re-walk the receiver expression to address it while the value was already
generated further up, so a receiver path rooted in a CALL was evaluated twice:
`mk().c.tick()` called `mk` twice, the mutation landed in the second result and
the first was discarded, silently, exit 0. Pre-existing and reachable only for
`&var self` / cell / `borrows` receivers — the flip puts every aggregate
`&self` call on those arms, which is why it was fixed here rather than filed
and left. `_receiver_path_is_lvalue` is the guard; the pin is
`examples/receiver_temporary_evaluated_once.saw`.

## (c) `borrows` accessors — assert no double handling

**Asserted, in codegen.** The place lowering is entirely source-level: after
`place_transform` the accessor is an ordinary method taking an extra `__window`
closure parameter, and `sawc/codegen/` contains no place-specific receiver
handling at all. After the widening a plain `&self` aggregate method and a
`borrows` accessor take the identical arg-0 path. The `place_self_by_pointer`
disjunct is kept, not redundant: it still carries a `borrows` accessor on a
PRIMITIVE receiver, which the aggregate widening does not reach.

**One consequence to record.** Two typechecker rules refuse a write through a
shared `&self` receiver — `place_uses`'s window-write refusal and `statements`'
`&var self`-method-on-a-field refusal — and both explain themselves in terms of
"the write lands in the callee's copy and is discarded". After the flip there
is no copy: those rules stop preventing a silent no-op and start preventing a
real write through a shared borrow. The rules are unchanged and now strictly
more load-bearing; their prose is stale and is U3's to fix.

## (d) The coroutine transform's frame-resident receiver

**Asserted, with IR evidence.** `coro_transform` strips `self` from the
parameter list and holds the receiver as a `__recv` frame field typed
`UnsafeRef<T>` = `{ %T* }` — a POINTER — for `&self` and `&var self` alike, and
rewrites every `SelfExpr` to a `deref()`. A suspending method emits no instance
signature at all, so the declaration site never runs for one.

Nothing in the frame path changes: no frame layout moves, no `__release` glue
moves, `--emit-frame-layout` is unaffected. The flip's effect here is
convergence — the sync path and the coroutine path now AGREE on the receiver's
shape, which removes a divergence the transform previously reconciled by hand.

## Two facts recorded for the lead, neither acted on

**1. `noalias` on a cross-thread receiver.** `TaskGroup` is not cell-carrying
(20 fields, eleven `Vector`s, no `Atomic`), so its ten plain-`&self` methods —
`count`, `__lock`, `__unlock`, `__notify`, `__gen_at`, `__stale`,
`__stale_sync` and the reactor quartet — flip. `__stale_sync` takes its
receiver copy at the CALL, i.e. before `self.__lock()` runs, so the flip
REMOVES a pre-lock unsynchronized snapshot of storage other threads write. The
sweep's caution is that `noalias` could license hoisting a load back above the
lock at the IR level. It should not here: `self.__lock()` is passed the
receiver pointer, so the lock call is based-on the noalias argument and the
load cannot move across it. The full suite's MT lanes are green. Recorded
because the reasoning, not a test, is what rules it out.

**2. The primitive fence is observable, and stays as ruled.** Brief §4 keeps
primitive receivers by value on the grounds that no construct can observe the
difference. The probe shows one can: `(&self) as UnsafePointer<Int>` inside
`extension Int { func f(&self) unsafe ... }` compiles today with no fence and
yields the callee's spill address, so `p.addr() == (&p) as UnsafePointer<T> as
Int` is `false` for `Int`/`String`/payload-free enum and, after the flip,
`true` for every struct. Values are unobservable either way — a read gives the
same bits, a write is discarded — so this is address identity only, and it is
NOT a regression: primitives behave identically before and after. What the flip
introduces is the type-dependent ASYMMETRY, where today the predicate is
uniformly `false` for `&self`. No corpus site relies on either answer. Left as
ruled and filed as DF-293c for the user, since §4's "if observable, align it"
and "primitive receivers stay by value" point opposite ways and that is a
ruling to make, not one to infer.

## Coverage and blind spots

Swept: `git ls-files '*.saw'` = 2,707 files (`examples/` 2,176, `sawc/std` 31,
`sawc/rt` 18, `blade/` 34, `libs/` 13, `devtools/` 9, `selfhost/` 11,
`tests/freestanding` 20), by a brace-matched receiver scanner plus targeted
greps for every textual form of a self-address; and `sawc/` Python by exhaustive
`ir.FunctionType` enumeration plus a `function_type` pass to catch signature
copying.

Not covered: an address derived inside a generic body or trait default body is
visible only through instantiation, and the Saw-side sweep is textual; the
`sawos` repo is outside this tree and references sawlang one way only; and the
MT reasoning in fact 1 is argued from the code path, not reproduced under
contention. The full battery is the backstop for all three.
