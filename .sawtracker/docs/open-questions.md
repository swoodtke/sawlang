# Open questions for the user

The lead keeps this list while the user is away (user direction, Sep 29).
- **Reversible questions** are decided by the lead, with the Air's input, and recorded here as "decided, for review".
- **Fundamental questions** wait here for the user. Work that doesn't depend on them continues meanwhile.

Newest first within each section. When the user rules, the entry moves to "Resolved", with the ruling and where it is recorded.

## Waiting for the user (fundamental)

### Q-precedence. Which text wins when LANGUAGE_SPEC and an SL design doc disagree? (Oct 9; the Air's m411; SL-479)
CLAUDE.md says only 'LANGUAGE_SPEC.md is authoritative for meaning'. Today two conflicts went opposite ways, each correctly. In D27 the spec beat SL:borrowing §2.7, which restated a rule that design 219 later replaced. In m410, SL:borrowing §3/§9 beat the spec, because §9 records a RULED retirement the spec text predates.

**Proposed rule:** a Ruled section of an SL: design doc, or a §9-style retirement, supersedes the spec text it names; otherwise the spec holds. The spec is then rewritten to the ruling (SL-479), so the conflict is temporary.

**Asking you:** may this sentence go into CLAUDE.md's opening paragraph and compiler/README.md? Until you answer, the lead applies it as stated. The stale spec passages are now rewritten (SL-479 and SL-482, both merged), and writing the rule down is SL-489.

## Open, for the lead to decide with the Air (reversible)

The lead hasn't decided these yet. Each one moves to "Decided" with its reasoning when it is settled.

### O4. The shape of Map's entry iterator (Oct 10; SL-489 item 3, docs489)
SL:borrowing §2.6 says collections implement `LendingIterator`, but it names no Map iterator. It gives no method name and no item shape. A map entry is a key and a value, so the item would be either a tuple of places (§7's tuple lends are a separate rule) or a pair struct. Until this is settled, the spec's Map "Iteration" says `Map` declares no iterator yet, and its visitors and snapshots are the iteration forms.

O1 to O3 are decided as D31 to D33.

## Decided by the lead, for review (reversible)

**D2–D21 were all accepted by the user on Oct 9, "for now".** They are revisited if a choice becomes less optimal as we learn more. Nothing in this section is waiting for review.

### D33. No expression forms a value of a `borrows` function type yet (Oct 10; SL-489 item 6, was O3)
The spec lets a function type carry `borrows` or `borrows(sync)` (`syntax.type.func-borrows`), and a `borrows(sync)` value does not convert to a plain `borrows` type. Nothing says how such a value is made. Two ways are closed:
- **A method reference:** the grammar has none.
- **A closure literal:** a closure has no receiver, and §2.7 refuses a `lend` rooted in a parameter, `&var` included.

**Decided:** in this language, the type describes methods: a trait requirement, and a call through a bound or an `any Trait`. No expression produces a value of it. Writing the type is legal, as the grammar already says. The spec says so plainly where it introduces the type.

**Rejected:**
- Admitting a closure that forwards a parameter's place. That widens §2.7's root rule, which deliberately keeps "lend what a caller handed you" out for now.
- Inventing a method-reference form inside a docs patch.

**Reversal or growth:** a method-reference design lists it in SL:borrowing §10 (Deferred). Admitting values later is compatible with today's text.

### D32. `--emit-docs` reports a `borrows` accessor's declared receiver, with a separate lend record (Oct 10; SL-489 item 5, was O2)
Stage 0 reports the receiver kind `window`, meaning "a read borrows shared and a write borrows exclusively, chosen at each use site" (design 146). The exception is an accessor that writes `self`, which it reports as `borrows-var`. SL:borrowing §3 retires use-site mode inference: the root charge follows the declaration. So `window`'s premise is gone.

**Decided:**
- **The receiver:** the `self` kind is read off the declared receiver, as for any method. `&self` is `borrows` and `&var self` is `borrows-var`.
- **A separate `lends` record** holds the facts the receiver can't show:
  - the lent type (`&T`, `&var T`, `&T?`, or a borrowing struct);
  - the root charge from §3's table, `shared` or `exclusive`;
  - whether it is `borrows(sync)`.

  A cell-carrying `(&self) borrows -> &var T` is then `self: borrows` (it serves a `let` root) with `root: exclusive`. These are two facts that one kind can't carry.
- **A `@synthesize(shared)` twin** is a real overload, so it is emitted as its own item with `synthesized: "shared"`.
- `window` is retired.

**Rejected:** folding the root charge into the receiver kind. It would report a cell-carrying accessor as `borrows-var`, telling a reader it needs a mutable root, which D7 says it doesn't.

**Reversal:** keep a single receiver-kind field, and give the root charge a new kind value.

### D31. A forwarded `lend` picks the inner accessor by the outer's lent type (Oct 10; SL-489 item 4, was O1)
An outer `(&var self) borrows -> &T` forwards `lend self.data[i]`, and the inner type has both a `&self` and a `&var self` `[]`. §2.7 and §3 don't say which one runs. It matters: `Data`'s exclusive `[]` separates shared copy-on-write bytes, and its shared one doesn't (§4).

**Decided:** the outer's lent type plays the binding keyword for the `lend` operand.
- **Lending `&T`** is read like `borrow let`. Per §4, it picks the `&self` variant when one exists ("the least privilege that works"), and otherwise the exclusive one.
- **Lending `&var T`** is read like `borrow var`, and needs a writable inner lend.

The pick is made among the inner accessors the outer's receiver can reach (the Air, m426). A cell-carrying `(&self) borrows -> &var T` outer can therefore forward only an inner cell-carrying `&self` accessor. An inner `&var self` one is unreachable from `&self`, so that `lend` is refused. This applies at each accessor hop of the operand. The outer's own root charge is unchanged, because it is still exclusive from its `&var self` declaration. A read-only forward through `Data` therefore never separates bytes.

**Rejected:** picking by the outer's receiver (`&var self`, so always the exclusive variant). It would make a read-only accessor perform a write's side effects, such as a copy-on-write separation and its allocation panic.

**Reversal:** pick the inner variant by the outer's receiver.
### D30. A by-value capture of a type parameter: `[copy x]` is refused at the definition, `[x]` is an inferred requirement (Oct 10; SL-481, batch B2's question)
`[copy x]`, `[x]` and an implicit by-value capture of an `x: T`, where `T` has no `Copy` bound. Today typecheck records nothing for any of them, and MIR's `capture_copy` raises an INVARIANT for all three.

**Decided:** the two spellings follow design 219's two rules.
- **`[copy x]` is a spelled copy,** so it is refused at the definition (`capture.copy`). There are two exceptions. With `T: Copy`, the copy is silent. With `T: ExplicitCopy` on a bare `T`, MIR calls the bound's `copy()`. The same rule applies to a type that mentions `T`, such as `(T, Int)` or `T?`.
- **`[x]` and an implicit capture are silent copies,** so they are an inferred `Copy` requirement checked at each call. This is D27's funnel, the one a generic getitem uses. A call at `Int` is accepted, and a call at a NoCopy type is refused at the call site, as Stage 0 refuses it.
- **MIR's `capture_copy`** accepts the silent capture on the same terms MIR already uses for `v[0]` of a `Vector<T>`, which is clean today through typecheck and mir. The INVARIANT stays for `[copy x]` of an unbounded `T`, because typecheck refuses that first.

**Rejected:** refusing all three at the definition. That would make a silent capture of `T` stricter than a silent getitem of `T`, which is two rules for one fact. D27 rejected the same split.

**Reversal:** refuse `[x]` and implicit captures of an unbounded `T` at the definition with `transfer.implicit-copy`, and keep MIR's INVARIANT.

### D29. A plain subscript in a rendering or comparison position is a getitem (Oct 10; SL-482, spec482's question; the Air's probes)
`print(v[0])`, `"{v[0]}"`, `print("{}", v[0])` and `v[0] == w[0]` over a `Vector<Res>` with `Res: NoCopy`. LANGUAGE_SPEC's "Value reads" said these places are borrowed where they sit, and both compilers accept them.

**Decided:** each is a getitem, so a NoCopy element is refused, and an ExplicitCopy one needs `.copy()`. The in-place read is spelled `borrow v[0]`, which parses at all four positions in sawc2. This follows from:
- the user's §1 ruling, "if it looks like a copy, then just copy";
- §5.1: "plain subscripts are values and `borrow` subscripts are places; the spelling at the call site picks the role";
- §2.2's own example, `print(borrow doc.section("net").name)`.

Copy-tier elements are unaffected. SL-482 writes the rule into the spec, and SL-486 makes sawc2 refuse the plain forms.

**Rejected:** a per-position exception ("a position that keeps nothing borrows"). It would make a plain subscript's role depend on where it sits, which §5.1's spelling rule replaces.

**Reversal:** restore "Value reads" to borrow-in-place for rendering and comparison operands, and close SL-486.

### D28. "`&self` is read-only all the way down" stops at a raw pointer's pointee (Oct 9; SL-479, the spec rewrite agent's open question 1)
SL:borrowing §9 retires design 200's heap carve-out: a `&self` body may not write storage the receiver reaches, `self.rows[0].push(9)` included. §9 doesn't say whether that covers a write through an `UnsafePointer` field.

**Decided:** it doesn't. A write through a raw pointer writes the pointee, not the receiver, and the receiver's type is what declared the pointer unsafe. This matches the SL-472 capture rule, where the only unsafe allowance is a raw pointer's pointee, and sawc2's K150 row. std's `Task.cancel` relies on it. The LANGUAGE_SPEC rewrite (SL-479) states it this way.

**Rejected:** refusing the write, which would force every std type over a raw buffer to take `&var self` for an interior write it guards itself.

**Reversal:** refuse a write through a pointer reached from a `&self` receiver, and give std's `&self` writers through pointers `&var self` receivers.

### D27. A getitem in a generic body is an inferred `Copy` requirement, not a definition-site refusal (Oct 9; batch B1, SL-467 row P12; the agent's m405)
`let s = self.slots[i]` in a method of `Holder<K>`, where `slots: Vector<Slot<K>>` and `K` is unbounded. Two texts disagreed:
- **LANGUAGE_SPEC** (design 219) says a read out of storage the body does not own ("a field, a tuple element, an indexed place") is always a duplicate, so it is an inferred `Copy` requirement checked at each call site.
- **SL:borrowing §2.7** (and K15), with Stage 0 (design 146, DF-146e), refused a generic slot's getitem in the body itself.

**Decided:** the spec holds, because it is authoritative for meaning and it is the later, unified rule. P12 is accepted at the definition, and a call at a NoCopy `K` is refused at the call site. A concrete NoCopy slot's getitem stays refused at the definition. SL:borrowing §2.7 is corrected. Stage 0's definition-site refusal is a Stage 0 over-refusal.

**Rejected:** a getitem-specific definition-site rule beside design 219's, which would be a second rule for one fact.

**Reversal:** add the definition-site refusal for a getitem whose element type mentions an unbounded type parameter, and restore §2.7's wording.

### D26. An assignment through an accessor runs its right side before the accessor's prologue (Oct 9; U6d2, SL-460.p2; the Air's review)
In `g[k] = f()` and `g[k] += f()`, where `[]` is a `borrows` accessor, the order of the right side and the accessor's prologue (user code) is observable. Stage 0 runs `k`, then the prologue, then `f()`, unless the right side reads the root, in which case it runs `f()` first. So its order depends on what the right side mentions.

**Decided:** sawc2 always runs the target's operands (`k`), then the right side, then opens the window (the prologue), then writes. That is SL:borrowing §2.2/§5.4, "right side first, then the left borrow", and it matches Stage 0's own M38 hint, "the right-hand side is evaluated first". It is one order whatever the right side says, and an exclusive window is never open while the right side runs. A method-call receiver is different (SL-473): it opens before the arguments, as the spec's "the receiver is evaluated before the arguments" requires.

**Rejected:** Stage 0's content-dependent order.

**Reversal:** open the target's windows before the right side, and refuse a right side that reads the root (as `vv[0].push(vv.len())` is). This changes one branch of the assignment lowering.

### D25. A call argument's loan spans the whole call expression, with a two-phase receiver reservation (Oct 9; U6d2, SL-460; the agent's m393)
SL:architecture §3.6 says a `ref` loan lives until its last use. Under that rule alone, the spec's "Nested calls" refusals would be accepted: X45 `combine(bump(&var n), scale(&var n))`, where the first loan is dead before the second is taken, and X44 `p.total(reset(&var p))`, where the receiver's `ref` is taken after `reset` returns. The spec says both are errors: an argument's borrow extends over the whole call expression, nested calls included, and the receiver is borrowed for the whole call.

**Decided:** the spec holds. §3.6's last-use rule is general, and the spec refines it for call operands.
- Per outermost call expression, every reference WRITTEN as & or &var anywhere in its argument list (nested calls included) keeps its loan to that call's terminator; a nested call's implicit receiver borrow does not join (so combine(n.get(), bump(&var n)) stays legal; the Air's m394).
- A deferred receiver loan is reserved from the receiver's evaluation and activated at the call, as in Rust's two-phase borrows. While reserved it acts as a shared loan. Shared reads in the arguments stay legal (`v.push(v.len())`), and a write or exclusive borrow of an overlapping path conflicts (X44).
- A `window_open` receiver is not reserved but fully live from receiver position (SL-473).
- It is derived from U6d1's MIR source nodes, or an explicit MIR marker, whichever is exact.

**Rejected:** last-use extent only, which accepts X44/X45 as a spec divergence. It is sound, since no two references alias at run time, but it changes meaning the spec states.

**Reversal:** drop the extent and the reservation from borrowck, then reword the spec's "Nested calls" paragraph. X44 and X45 flip to accepted.

### D24. String's sentinel check is a relaxed atomic load, not a plain one (Oct 9; SL-466; the Air's SL-456.p2 review)
The spec's String section says a literal's sentinel refcount is checked with a "plain (non-atomic) load" before any atomic operation, and Stage 0 emits exactly that. The fact being read, "is this block immortal", never changes over a live block, so the result is right in practice. But in the C++/LLVM memory model a non-atomic load that races with another thread's atomic read-modify-write of the same word is a data race, and its result is `undef`. A relaxed (monotonic) atomic load compiles to the same instruction on every mainstream target and has no race.

**Decided:** the check is a relaxed atomic load. The builtin module gains `__saw_atomic_load_i64_relaxed`, alongside D23's three. `std/string.saw`'s `copy` and `deinit` use it, and the spec's String section says "relaxed atomic load". The property that matters is unchanged: a literal's block, which may be read-only, is never written. sawc2's backend emits a monotonic load. Stage 0's plain load is left as it is, since `sawc/` is frozen and the two compile to the same machine code.

**Rejected:** keeping the plain load, which is formally undefined behaviour under the model the backend targets.

**Reversal:** return to the plain load and the old wording. That is one intrinsic and two call sites.

### D23. Atomics are builtin intrinsics, and `Atomic<T>` is a `std/` type over them (Oct 9; U5b2, SL-456; the Air's c17)
Under "the builtins should not be magic", String's retain hook is written in Saw in `std/`, and it needs atomic operations: a plain load, `add`/`sub` with an ordering, and a fence. Stage 0 synthesizes `__saw_atomic_*` (and `__saw_string_*`) as IR bodies, and `sawc/rt/ABI.md` says a runtime must not provide them.

**Decided:** the synthetic builtin module gains a minimal set of atomic intrinsics, spelled as Stage 0's `__saw_atomic_*` helpers, so `rt/ABI.md` keeps one vocabulary. They are what no Saw source can declare, which is what the builtin module keeps under the ruling. They pull in no runtime, so they are freestanding-safe. `Atomic<T>`, where needed, is an ordinary `std/` type built on them.

**Rejected:**
- **`extern` declarations naming the synthesized helpers:** an extern claims a runtime provides the body, which ABI.md forbids for these.
- **A lang-item function role per atomic op:** that would be a role with no Saw body.

**Reversal:** expose atomics through a different spelling or layer. It changes only `std/`'s internals and the builtin table.

### D22. `case None` is declarable only in the Optional lang item (Oct 9; U5b1, SL-456)
Under the user's ruling that "the builtins should not be magic", `std/prelude.saw` declares `Optional<T>` as an ordinary enum. But `None` is a keyword, and GRAMMAR's `syntax.decl.case` takes an IDENT, so `case None` doesn't parse.

**Decided:** the grammar admits `None` as a case name in an enum declaration, everywhere, so the grammar stays context-free. A semantic rule refuses a `case None` declaration in every enum except the one bound to the Optional lang item, and the lang-item shape check requires it there, payload-free. The `None` literal and the `None` pattern keep their one meaning: Optional's case.

**Who and when:** U5b1 makes the grammar edit itself, in its own commits: GRAMMAR.md with a lint fixture, the reference recognizer and its corpus expectations, and sawc2's parser. Its boundary was extended for this in the lead's direct message. It lands no later than `std/prelude.saw`, and U5b1's gate includes `grammarcorpus` (the Air, t15).

**Rejected:**
- spelling the case another way and mapping `None` to it, which keeps magic in the mapping and changes a user-visible name;
- a compiler-supplied case, which is still magic.

**Reversal:** let `case None` be declared in any enum, with the literal resolved by expected type, which would change what `None` means.

### D21. Two typecheck readings from SL-447.p3's review (Sep 30; the Air)
1. **A suspending implementation is refused where it is coerced to `any Trait`,** not where it is dispatched. Stage 0 refuses at the dispatch, so a coercion that is never dispatched is accepted by Stage 0 and refused by sawc2. Refusing at the coercion is sound, and it is the site a modular checker can see: the dispatch may be in another module. Decision 3 of U6b3 rests on it.
2. **Exhaustiveness reasons over closed types at any depth.** `(Bool, Bool)` covered by `(true, true)`, `(true, false)` and `(false, _)` is exhaustive, and so is `A(X)`, `A(Y)`, `C` over nested payload cases. The spec's "never prove it on an **open** type" supports this, since `Bool` and enum constructors are closed. Stage 0 refuses both ("literal, range, and guarded arms do not prove exhaustiveness"). `compiler/` meets Stage 0's stricter rule regardless.

**Reversal:** (1) move the refusal to the dispatch; (2) require a wildcard wherever a tuple or nested payload is matched. Each refuses programs sawc2 now accepts, or the reverse, and neither touches `compiler/`.

### D20. In a generic body, a borrow after a by-value read makes that read a copy (Sep 30; U6b3, SL-447)
Design 219's inferred Copy requirement is per path (spec: "The rule is per PATH, not per mention"). A `T` local read by value once on a path is moved, and a second by-value read on the same path duplicates it. The spec doesn't say what a *borrow* after the by-value read means: `let a = sink(x); look(&x)`.

**Decided:** any use after a by-value read on the same path, a borrow included, makes that read a copy, so the body infers `T: Copy`. The function then works for Copy types and is refused at a call site with a move-only type, quoting both uses. The alternative, recording the read as a move and the later `&x` as a use of a moved value, would refuse the body at every type, including the Copy ones the requirement admits.

**Reversal:** record the move, and let the borrow check refuse the later use at every instantiation.

### D19. A `sync` body inside a generic is checked per instantiation (Sep 30; U6b3, SL-447)
SL:architecture §3.4 says a call through a generic bound is conservatively may-suspend inside a generic body, unless the requirement is `sync`. Read literally, a `sync` function, `deinit` or sync-typed closure inside a generic, calling a non-`sync` requirement through a bound, would be refused at the definition. That refuses `closure_captures_self.saw`, which Stage 0 accepts. The spec says suspension "inference runs per instantiation".

**Decided:** judged per instantiation. The generic's summary records the condition, `(refuses-when (sync T.Trait.req))`. A call site with concrete type arguments evaluates it, and refuses there when the instantiated requirement isn't sync-callable. The message names the generic's `sync` body and the requirement. A call site whose type arguments are themselves type parameters (`func outer<U: Trait>(u: U) { inner(u) }`) doesn't evaluate it. It composes it into its own summary, as `(refuses-when (sync U.Trait.req))`, so it is evaluated only at a concrete call further out (the Air, t14, verified on SL-447.p3). Naming a generic function as a value at an instantiation isn't in the language before self-hosting (SL-415), so no other use needs the evaluation. It is sound, because every concrete use is checked, and it accepts exactly the instantiations that are sync-safe. §3.4's "conservative inside a generic body" still holds for may-suspend (framing and the borrow check), which this doesn't change.

**Reversal:** refuse at the definition, and require the bound's requirement to be declared `sync`. That refuses programs sawc2 now accepts.

**Also recorded (U6b3):** the parking-module cross-check leaves out the executor intrinsics (`__saw_exec_*`), which serve the sync drive loop. So the derived set is channel, net, process, signal and task, and Stage 0 finds no suspending function in `std.taskgroup`.

### D18. An undeclared generic POD struct auto-conforms per instantiation (Sep 30; the Air, SL-447.p2 approval)
`struct Pair<T> { a: T, b: T }`, with no conformance written, then `Pair<Int>(…) == Pair<Int>(…)`. The spec's auto-conformance covers "trivial (POD) structs" and doesn't say whether a generic declaration qualifies. Stage 0 refuses it ("does not conform to `Equatable`"). sawc2 accepts it.

**Decided:** accepted. A generic struct's automatic Equatable and Hashable are judged per instantiation, like its Copy tier, which is already a rule over its arguments (U6b1's reading). So `Pair<Int>` qualifies and `Pair<String>` doesn't. One rule then answers "what does this type get for free", for every automatic trait. In a generic body, `Pair<T>` is not Equatable, since whether it is POD depends on `T`. Code generic over it writes the conformance, `@synthesize extension Pair<T>: Equatable` (the Air, t13).

**Reversal:** automatic conformance only for non-generic structs. That refuses programs sawc2 now accepts, and none of them is in `compiler/`.

### D17. A bare module static carries its declared type (Sep 30; the Air, SL:hazards t22)
`static SHIFT: Int = 3`, then `flag >= SHIFT` with `flag: UInt32`. The spec pulls two ways:
- "a named value carries the type it was declared with" says no adoption;
- a module `static` "may be a leaf" of a constant expression, which adopts, so `flag >= (1 << SHIFT)` works. It doesn't say whether a lone leaf counts.

Stage 0 adopts only an `Int` static, only as an operand, and then crashes in codegen (SL:hazards L21).

**Decided:** a bare static carries its declared type, as every named value does. It adopts only as a leaf inside a constant expression.
- `flag >= SHIFT` is refused, with the hint `SHIFT as UInt32`.
- `flag >= (1 << SHIFT)` builds.
- `let y: Int = SHIFT + 1` is fine, since both are `Int`.

The reader sees the conversion written, and no static silently changes width.

**Reversal:** let a bare static adopt as an operator's peer, or in every slot a constant adopts in. That only admits programs refused today.

### D16. `h.f(3)` on a function-typed field calls the field's value (Sep 30; the Air, SL-447.p2 review)
A struct field of function type, `struct H { f: (Int) -> Int }`, called as `h.f(3)`: the spec never shows this spelling. Stage 0 accepts it. The grammar has no unapplied method reference, so `(h.f)(3)` already means `h.f(3)`, and no other call spelling reaches the field.

**Decided:** accepted. When the type has no visible method `f`, `h.f(3)` calls the field's function value, and the call's role is `value`. When a method `f` is visible too, the call is refused, naming both, with the fix-it `let g = h.f; g(3)` for the field. Extensions are import-scoped (design 142), so "the method wins" would let an added import silently retarget the call. Refusing keeps the meaning local, at little cost, since a field and a method sharing a name is rare (the Air, t12). Stage 0 lets the method win.

**Reversal:** refuse it, and require a local binding (`let g = h.f; g(3)`).

**Two related readings keep the refusal, since the spec doesn't describe the form:**
- `t[0]` on a tuple (the spec has only `.N`);
- an else-less value `if` yielding an optional.

The corpus programs that use them (`arrays.saw`, `named_tuple_basic.saw`, `nested_if_iflet_tail`) are re-aimed at the next corpus migration.

### D15. Auto-wrap and erasure where the spec is silent: the strictest stated reading (Sep 30; U6b2, SL-447)
The spec states how deep an implicit `Optional` wrap goes, whether a `Result` wrap applies, and whether a concrete error erases to `Box<any Error>`, for some positions and not others:
- **argument:** one optional level, the Result wrap, no erasure;
- **`let` and the return positions:** any depth;
- **return:** erases.

sawc2's typecheck now enforces a per-position matrix through one conversion path. The full table, with a spec quote per cell, is in `compiler/tests/typecheck/README.md`, "The wrap and erasure matrix". Where the spec is silent:

**Decided:**
1. **No erasure at `let`, assignment or `static`.** The spec states erasure only at the return boundary, since it needs the allocator that position supplies.
2. **One optional level** at a `static`, a parameter default, a compound-assignment right side, an operand or comparison, and a `??` fallback.
3. **No Result wrap** at an operand, a comparison or a `??` fallback, since none of them is a declared Result slot.
4. **Structural limits:**
   - a Result wrap inside an optional wrap (`Result<Int, String>?` fed `10`) is refused, since only "`Result<T?, E>`… innermost first" is stated;
   - a second nested Result wrap is refused.
5. **Implicit `Box<any Trait>` erasure** is refused for any trait but `Error`. Owned boxes are built with `.make`.

Every refusal is `type.mismatch`, and its message says which limit applied. Nothing in `compiler/` relied on the looser reading, and the frozen compiler agrees where it has a rule.

**Reversal:** loosen any cell. That only admits programs refused today.

**Also found:** the spec's "a static is never optional" isn't enforced yet. It is queued for U6b3.

### D14. An extension head that omits a defaulted type parameter is refused (Sep 30; the Air, SL-447.p1 review)
`Vector` is `Vector<T, A: Allocator = GlobalAllocator>`. `extension Vector<T> { … }` has two readings:
- **a specialization,** with the default filled, so `A = GlobalAllocator`, and the methods exist only for the global allocator;
- **a rename,** generic over `A` too, with the methods existing for every allocator.

Stage 0 accepts it. std always writes the defaulted parameter out (`extension Vector<T, A: Allocator>`). The spec doesn't say.

**Decided:** refuse it, with a fix-it that writes the parameter out. That gives the rename, generic over every allocator. To specialize on purpose, write the argument: `extension Vector<T, GlobalAllocator>`, which is a specialized extension, `slice.not-yet` for now. The reader then sees which one is meant, and no program changes meaning silently.

**Which rule names a head that both specializes and omits the default** (`extension Vector<String>`, `extension Vector<Int>`, the only form tracked code writes; the Air, t10): the specialization, as `slice.not-yet`. That is the primary fact, and writing `A` out still leaves a specialization. D14 applies only to a head whose written arguments are all the extended type's own parameters, a pure rename that omits one.

**Reversal:** accept the short head as one of the two readings. That only admits programs refused today.

### D13. Resolve reads a lone name pattern as a case when an enum in the module's import closure declares that name (Sep 30; U6a, SL-445)
GRAMMAR's `syntax.rule.name-pattern` leaves it to resolution whether a lone name in a pattern, `case North` or `case x`, names a payload-free variant or binds. The scrutinee's type decides which enum it could be (`syntax.pat.refused-qualified-variant`), but resolve runs before types exist. Stage 0 decides by capitalization.

**Decided:** resolve reads a lone name as a case when an enum in the module's import closure declares a payload-free case of that name, recording the candidates. Otherwise the name binds. The closure is the module's own enums, those of the interfaces it imports (transitively), and `builtin` with the prelude. A scrutinee's type is reachable only through that closure, so no case it could name is lost, and the decision stays local to what §3.3 takes as input (the Air, t8). Typecheck then picks the candidate from the scrutinee's type, and refuses a candidate set with none in that enum ("`x` names no case of `T`"), rather than falling back to a binding.
- It is never silently wrong. A case of the scrutinee's own enum always resolves as that case. The only cost is a spurious refusal when an unrelated enum's case shares a binding's name, and the fix is a rename.
- It agrees with Stage 0 on all of `compiler/`.
- **Pins:** `case n if n < 0` over an `Int` stays a binding when no enum in the closure declares `n`. An unrelated module's case of the same name, outside the closure, changes nothing. The spurious-refusal message names the case the pattern was taken for and suggests the rename.
- U6a's first cut scoped it program-wide. SL-445.p1's revision narrows it.

**Reversal:** capitalization (Stage 0's rule), or deciding in typecheck with bindings scoped after it.

### D12. Resolve binds builtins to a synthetic `builtin` module, and the prelude is an inclusion table (Sep 30; the Air, SL-445 c1)
§3.3's binding kinds have no slot for the declarations nothing declares: the primitive types, `String`, the Stage-0-synthesized `Optional`/`Result`, `print`/`panic`/`assert`/`sizeof`/`alignof`, and `Void`/`Never`. Stage 0 also defines the prelude by exclusion (`IMPORT_REQUIRED_STD_*`).

**Decided:**
- Builtins are declarations of a synthetic `builtin` module, one table, and bind like any other: `String` is (builtin, String).
- The prelude is one inclusion table in resolve (design 82's curated core), checked once against Stage 0's computed set over today's std. The design-255 gated tier derives from it.
- An inclusion list fails safe: a new std module is gated by default.

**Reversal:** a different home for builtins (for example, the new std declaring them), or an exclusion list.

### D11. `syntax.lex.ascii-identifier` covers every non-ASCII character outside strings and comments (Sep 30; the Air, SL-410 c4)
§2.7 words the rule as "a letter outside ASCII cannot start or continue [an identifier]". sawc2's lexer refuses every non-ASCII character outside a string literal or a comment alike, as "Unexpected character": `é`, `ï` and `→` all get that. Naming the rule only for letters needs a Unicode letter table in the subset.

**Decided:** reword §2.7. Saw source is ASCII outside the text of string literals and comments, and an interpolation's expression is source (the Air, c6). Any other character there is refused as `syntax.lex.ascii-identifier`. The message names the character and says that identifiers and source outside strings are ASCII.
- Every such character is refused either way, so only the name changes. No program changes meaning.

**Reversal:** narrow the rule to letters with a letter table, and give a non-letter its own name.

### D10. A `{` right after `while` opens the infinite loop's body (Sep 29; U4i)
GRAMMAR.md is ambiguous at `while {`. The recognizer accepts `while { a } { }` as `While.conditional` with a closure literal as its condition. It finds `while { a }`, then a line break, then `{ }` ambiguous, since the infinite loop followed by a closure statement is also a tree. sawc2 and the frozen compiler both read `while {` as the infinite loop, and 81 tracked files use that form.

**Decided:** add a §13 rule that a `{` right after `while` begins the infinite loop's body, never a condition. The recognizer gets the matching filter. A closure condition either can't typecheck, since a closure is not a `Bool`, or it is refused. An immediately called closure, `while { check() }() { step() }`, would typecheck under the old reading, but under D10 the `{` opens the body, so the text is refused rather than re-read (the Air, t6). The frozen compiler refuses it the same way. So no program silently changes meaning.
- **To pin:** `while { c }() { }` is refused by the new rule's name, and `while ({ c }()) { }` is accepted as a conditional loop.
- **sawc2 changes too** (the Air, t7). Today sawc2 refuses the first at the `(` as `block-tail`, whose hint, "parenthesize the loop to use its value", points the wrong way. The unit makes sawc2 name the new rule at that token instead, with the hint `while ({ check() }()) { step() }`. The frozen parser's refusal of the second pin is §16's existing `syntax.expr.call` row (SL-73), not a D10 matter.

**Reversal:** drop the rule and parenthesize, as in `while ({ a }) { }`.

### D9. Std accessors whose body only reads get a shared twin (Sep 29; SL-421)
SL:borrowing rules twins for `Vector.[]`, `Vector.find` and `KeyedPlace.find` only. tests/corpus reads six more std accessors in a shared position: a `let` root, a `&` param or a capture of a `let`.
- `JsonValue.as_array` and `as_object`;
- `Map.[]` (the place accessor);
- `Box.value`;
- `std.compiler.frame` `Slot.value`;
- `UnsafeRef.deref`.

Each is declared `(&var self)` in the frozen std, and each body only reads: it matches or guards, then lends.

**Decided:** in the new std, a std accessor whose body only reads gets a `@synthesize(shared)` twin (§4), so these six serve `borrow let` on shared roots. SL-421's corpus decisions assume it.

**Reversal:** give one of them no twin, and re-aim its corpus files as refusals, or respell them through a mutable root.

### D8. Getitem and setitem derivation with an accessor pair (Sep 29; SL-420 finding 4)
§5.2 states the derivation for a type that declares "only the place accessor". **Decided:** a type that declares a pair derives getitem from the `&self` accessor and setitem from the `&var self` one. That is the reading SL-420's re-aims use. **Reversal:** restrict derivation to single-accessor types.

### D7. What the root column of SL:borrowing §3's table means (Sep 29; SL-420 finding 3)
§3 says `(&self) borrows -> &var T` (`Mutex.lock`) holds its root "exclusive", yet `lock()` must work on `let`, `&self` and static roots (§8, §8a). **Decided:** the column is the *overlap* charge: no other use of the root while the borrow is open, so `m.lock()` inside its own window is refused, as §8 says. Whether the root must be *mutable* comes from the receiver. A `&var self` accessor needs a mutable root; a cell accessor takes `&self`, so `let`, `&self` and static roots serve. The clarification is in SL:borrowing §3 (r24). **Reversal:** a cell accessor would need a mutable root, which contradicts §8a.

### D6. How a signed width suffix bounds a literal (Sep 29; the Air, SL:hazards t21; SL-435)
GRAMMAR.md §2.7 `syntax.lex.int-range` says a literal must fit "in its suffix's width", but not how a signed width counts. Stage 0 and sawlex both check the unsigned range, so `255_i8` lexes, and Stage 0 wraps it to -1 (S7's signed-suffix face).

**Decided:** state it in two layers.
- **The lexer** checks the width's unsigned range, so `256_u8` and `256_i8` are lexical errors.
- **A later stage** holds a signed suffix's literal to the signed range. It allows exactly 2^(w−1) as the operand of a unary minus (`-128_i8`), since the lexer cannot tell a negation from a subtraction.
- §16 gains a `defect` row for Stage 0's silent wrap.

**Why reversible:** it only refuses programs that silently wrap today. It changes no meaning a correct program has. The subset checker gets the matching rule (SL-435).

**Reversal:** reword §2.7.

### D5. The depth limit decides no reading (Sep 29; U4c)
A speculative generic list that the depth limit cuts short is refused with `syntax.rule.depth-limit`. It is not re-read as comparisons, because otherwise the depth budget could change what a program means. A speculation that fails for any other reason still gives its levels back, and a depth cell pins that.

**Decided:** as implemented in U4c (merged ee6d0143). The Air confirmed that making the refusal final is right: `g(a < b, b < c, c >> (d))` is a generic call, so a re-read could change meaning.
- **Refined (the Air's review of p3):** a *flat* valid program, `f(x0 < x1, …, x256 < x257)`, was refused because each pair speculated one nested list.
- **Fix, queued at the start of U4d:** skip speculating when no closing `>`, `>=`, `>>` or `>>=` comes before the enclosing bracket closes, since such a list could never close. That accepts the flat case and keeps D5 for the balanced one.
- **Also queued:** GRAMMAR.md §11 will state that a speculated list charges depth while its contents are parsed, and that a list cut short by the limit is refused. A cell pins the flat case.

### D4. When the parser names a refusal `generic-or-less` (Sep 29; U4c)
Suppose a list parses and the follow rule rejects it. If the token after its `>` can continue the expression (`continues_postfix`), and the comparison re-read then fails with a plain error or a comparison chain starting at that `<`, the parser reports `syntax.rule.generic-or-less` at the `<`. Otherwise the comparison reading's own error stands, so `a < b > c` stays `refused-compare-chain`. The Air checked 12 shapes in SL-424.p3's review: where the reference names a rule, the parser names the same one at the same `<`.
- **Evidence:** this matches every corpus case and U4c's differential of about 200 texts: `a<b>` before a line break, `a<b> - 1`, `a<b>[0]`, and `x as T<a, b> c` staying `parse-error`.
- **Caveat:** it is a model of the recognizer's "the chart accepts, a filter refuses" condition, not a derivation of it.
- **Correction (the Air, SL-424 c31):** the 12-shape check compared against the reference's raw "refused by" rule, which is README Refusals step 3. Step 2 comes first: a removed production whose enabling alone makes the text parse. Under step 2, `a<b> - c` and `a<b>[0]` are expected to be recorded as `refused-compare-chain`, since each parses as a chain once chains are enabled. U4d fixes the parser to follow the classification, and sweeps the shapes with `cases.py`.
- **As implemented in U4d (SL-424.p4):** when re-reading a rejected list as comparisons gives a chain that parses whole, the parser reports `refused-compare-chain`. Otherwise `generic-or-less` stands, under the `continues_postfix` condition above.
  - In 26 shapes, the chain flips are `- c`, `[0]`, `* c`, `& c`, `.. c` and `-(c)` after the `>`.
  - `!` and a line break keep `generic-or-less`.

**Decided:** accept the model. If SL-410 (the recognizer naming every refusing rule) produces a case that disagrees, the recognizer's name wins, and the parser follows it.

### D3. A checker rule refusing `try?` in `compiler/`, an S23-style exception (Sep 29; the Air's t20 on SL:hazards)
**The finding:** `try?` never releases the error it discards (SL-429, SL:hazards S3), and it reaches Stage 1 because the compiler is sync code. The leak ruling gives leak-only hazards no checker rule. You granted S23 an exception because a parser's hot paths would leak per token.

**Decided: add the rule** as the same kind of exception.
- **Why:** a parser's speculative "try this, else fall back" paths are where `try?` would naturally appear, so the leak would be per attempt. The rule is structural (refuse a `try?` expression), costs nothing today because `compiler/` has none, and its Instead is `match`.
- **Reversal:** delete the rule.

Landed in SL-432.p1, which the Air approved.

### D2. SL-426's `bhead` cell: recode §12 from P to S (Sep 29; the Air's t1)
Correction: the lead first wrote "B", which is not a §12 code. The SL-426 agent used **S** ("parses; a later stage refuses the construct in this position"), whose legend matches this decision's reason word for word. Y is the alternative, since a borrow head "may be any expression" (SL:borrowing §2.1). Either is one character, and the generator treats them alike.
**The finding:** §12 codes `syntax.borrow.block` × `bhead` as P (parenthesized only). But `syntax.rule.head-reset` admits a nested borrow construct's body in any head (SL-426 c1), so GRAMMAR.md's text says `borrow let x = borrow let x = a { x } {` parses. The recognizer agrees.

**The options:**
- (a) a new refusal rule, which would be a new language rule and so the user's call;
- (b) recode the cell S, a §12 correction that matches the text.

**Decided: (b).** The type layer refuses the case either way, since a block's value is not a place, so no program changes meaning.
- **Reversal:** a later ruling for (a) adds the rule and flips the cell back.
- **`cond`,** SL-426's other cell, is a plain recognizer fix: borrow-form's "at an `if` head … unwrap" clause already backs its P.
- Both land when SL-426 is dispatched, before U4h.

## Resolved

### SL-493. An alias constructor over a constant is a constant: `static A: Byte = Byte(65)` (Oct 10; the USER's ruling)
LANGUAGE_SPEC said `static MINUS_SIGN: Byte = Byte(45)` is refused "because a constructor call is not a constant expression", and Stage 0 refuses it. But in a `let`, `Byte(45)` is the only spelling for an alias over a fixed-width type. So the one conversion that changes nothing about the value was illegal in exactly the slot that wants constants.

**Ruled:** accept it as a constant. The lead's scope:
- A type alias's constructor applied to a constant expression, `A(e)`, is a constant expression.
- It folds to `e`'s value at the alias's underlying type.
- It gets the same fit check a bare literal gets, so `Byte(300)` is "constant expression 300 does not fit in `UInt8`".
- It is accepted in every constant position, not only static initializers, since all of them share one evaluator.

Function calls in general stay refused (tier 3), as do `init` bodies and non-alias constructors.

**Where it lands:** the spec's alias passage and the tier-2 list, typecheck's fold and the evaluator (misc459, SL-459), and SL-493's refusal funnel, which must not refuse this shape. Stage 0 still refuses it, and it is frozen, so source that Stage 0 compiles keeps the bare-literal spelling.

### Escaping closures stay refcounted `Copy`, not move-only (Oct 9; the USER agreed with the lead and the Air)
The user asked whether escaping closures should be move-only. After SL-469 and SL-472 the shared env is immutable and never consumed, so sharing is semantically invisible, and move-only would cost copyability for callbacks held twice and the Copy tier of every struct with a closure field. The refcount's only job is deciding when the env's owned captures are freed. **Decided:** keep the refcounted Copy model. **For the codegen unit, measure two observable-equivalent optimisations:** a non-atomic refcount (closures never cross threads; spawn takes an explicit capture list), and copying a closure whose captures are all trivial bitwise, like a plain function. Revisit the model only if a `Send` closure type is ever added.

### SL-472. Captures are `let`: no by-value or move capture is writable in any closure body (Oct 9; the USER's ruling)
"For a non escaping closure capturing the vec by ref would be the correct behavior imo. For an escaping closure no captures should be modifiable ever." Read as one rule: a by-value or move capture is a `let` in the body, and the only way a closure changes outside state is a `[&var x]` capture, which only a non-escaping closure may take. It replaces design 132's lost-write rule and its heap-container carve-out, which let an escaping closure's copies share and change a captured `Vector` (both compilers print `2 3 4`). **Confirmed by the user:** `&self` interior-mutability methods (`Mutex.lock`) and writes to a captured raw pointer's pointee stay legal, both by design ("Mutex is modifiable and pointers are unsafe and modifiable").

### SL-469. An escaping closure that consumes a `move` capture is a compile error (Oct 9; the USER's ruling)
An escaping closure is a shared, refcounted value, so a body that consumes an owned capture takes it from storage that other copies, later calls and the env's destructor still see: a double free in both compilers (DF-255a, V49). **Ruled by the user:** a consuming use of a `move` capture inside an escaping closure body is refused at compile time, with a hint toward the spellings that work: capture an `Optional` and `take()` it, pass the value as a parameter, or use a non-escaping closure. Non-escaping closures keep the take-once rule. The runtime once-flag (an atomic swap per consuming call, and a panic on the second) was rejected.

### W4. How a generic body names its type parameter's associated type (user, Oct 9): (a) `T.Item`
A trait declares an associated type: `trait Container { type Item; func get(&self, i: Int) -> Item? }`. Inside the trait and its conformances, bare `Item` names it. The spec shows nothing for a generic function over the trait, which has to say "the `Item` of `T`":

```saw
func first<T: Container>(c: T) -> ??? { c.get(i: 0)! }
```

**Today:**
- Stage 0 accepts bare `Item` there, resolved through `T`'s bound.
- The new compiler has no spelling yet. Bare `Item` is not in scope. `T.Item` parses as an ordinary qualified type path, but resolve refuses it: "`Item` cannot be named through a path here". Stage 0 refuses it too, as "`T` is not a module qualifier here" (the Air, t9).
- Usage: three corpus test programs, and nothing in std, Blade, libs or `compiler/`. So no real code depends on either answer, and the bootstrap doesn't wait on this.

**The options:**
- **(a) `T.Item`,** as in Swift (Rust writes `T::Item`). The reader sees which parameter the type belongs to, and it stays unambiguous with two parameters, or with two bounds that both declare `Item`. It needs no GRAMMAR change. It needs a resolve rule: a type path headed by a type parameter names the associated type its bounds declare, and an ambiguous or absent one is refused. Typecheck then needs a projection key.
- **(b) Bare `Item`,** found through the bounds of the type parameters in scope, as Stage 0 does. An ambiguous name is refused. It is shorter, but a reader can't tell where `Item` comes from, and adding a bound elsewhere can make it ambiguous.
- **(c) Both,** bare as a shorthand when it is unambiguous.

**Recommendation: (a).** Reader-visibility trumps inference (the design doctrine), and `T.Item` matches the `Enum.Case` qualification the language already uses. The three corpus programs would be re-aimed.

**Ruled (user, Oct 9): (a), `T.Item`.** Implementation is SL-453: a resolve rule naming the bound's associated type through a type-parameter-headed path, with ambiguous or absent ones refused, plus typecheck's projection key. Bare `Item` stays refused, and the three corpus programs are re-aimed.

**Until SL-453 lands:** resolve refuses the bare form as `slice.not-yet`, "an associated type named through a type parameter's bound", which no program in the bootstrap slice meets.

### W3. An absent conditional write evaluates its right side (user, Sep 29): (a)
**Ruling:** `borrow var v.find(9)?.value = loud(3)` calls `loud(3)` whether or not the place is present. Every assignment has one order: the right side first, then the left borrow. `?` skips only the write. The block form `if borrow var p = v.find(9) { p.value = loud(3) }` computes the value only when present.
- **Recorded in:** SL:borrowing §2.2 (r24).
- **This changes today's optional chaining,** which skips the right side (LANGUAGE_SPEC, Optionals: "the RHS is skipped entirely on short-circuit"). GRAMMAR §15 lists the passage (SL-437).
- **No real program uses it** (the Air, t5). The tests/corpus files that pin the skip are re-aimed in SL-438, `place_assignment_targets` among them.

### W2. The one-element tuple pattern (user, Sep 29): (b2)
**Ruling:** a one-element tuple pattern is spelled `(p,)`, as in expressions and types. A bare `(p)` in a pattern is refused, with a hint naming `(p,)`. No text silently changes meaning, and no real program in sawlang, sawtracker or sawos uses `(p)`.
- **GRAMMAR.md §8:** `tuple-pattern` gains the `(p,)` form, and `(p)` becomes a removed form with its fixit. §16 records sawc, which reads `(p)` as a one-tuple.
- **The parser:** U4e's one commented spot in `parse_tuple_pattern_body` flips, with its three pins.
- **Trailing comma (user, Sep 29): allowed.** A tuple pattern of any length takes one trailing comma, `(a, b,)`, as tuple expressions do. The Air's pin `case (a, b,)` flips from refused to accepted. **Variant payloads too (user, Sep 29, revising "tuples only"):** a variant's payload list also takes an optional trailing comma, so `Some(x,)` is accepted, matching the call that builds the value (the Air, t4). The user's reason: refusing it slightly complicates parsing and buys nothing. U4e's `case Some(x,)` pin flips to accepted.
- **One element:** in a tuple pattern the comma stays required (`(p,)`, with `(p)` refused). In a payload it is optional: `Some(x)` and `Some(x,)` are the same.

### W1. `borrow` bindings at `while` and `guard` heads (user, Sep 29): (a) for `while`; `guard` takes none
**Ruling:** a borrow binding at a `while` head is the optional-place unwrap, as at `if`: `while borrow var e = it.find(&k) { … }` loops while the place is present. A `guard` takes no borrow binding (the user: "Guard can't use borrow since its body is in the else").
- **`while`:** the window is the loop body. The head is evaluated again each iteration, after the previous window closes. The bare borrow-block condition is refused there, as at `if`. The parenthesized `while (borrow let e = m[k] { e.ok }) { }` stays a condition.
- **`guard`:** a borrow binding in its head is refused by name, with a hint pointing at `if borrow … { } else { … }`. The parenthesized block stays a boolean condition.
- **To update:** SL:borrowing §2.4, GRAMMAR.md §9 (where a binding stands), `syntax.rule.borrow-form`, and §12's `cond` cells, with corpus cases for both hosts.

### D1. Autonomy settings for this stretch (user, Sep 29)
- **Decision policy:** as in this doc's header.
- **One agent at a time.**
- **The work order is the lead's to decide,** consulting the Air when useful. The current plan interleaves the parser units with side-queue items between units: SL-426, SL-410, SL-412, the lexer halves of SL-408 and SL-413, SL-405, SL-420 and SL-421.
- **Nothing is off-limits** unless the lead needs the user's feedback.
