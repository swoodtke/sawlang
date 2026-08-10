# Design 186 — `UnsafeMutableInterior<T>`: interior mutability without the name list

**LANDED Aug 9 — all eight units. Seven commits, the full suite green at each
(1600 passed, 3 pre-existing xfails at the last). Units 1 and 2 landed as ONE
commit: the property has to be TRUE for `Atomic` in the same commit that starts
consulting it, so `Atomic`'s field migration (unit 4's first sentence) came with
it. One pin flipped and was renamed (`static_const_expr_init`, DF-185b, which
tier (b) absorbs as planned). Four findings filed: DF-186a (a deferred
`Atomic`-copy-tier question, the one place the ruling could not be taken
literally without re-tiering every struct holding an `Atomic` — see the tracker),
DF-186b and DF-186d (both PRE-EXISTING, found and fixed here), DF-186c (the two
language gaps that keep the Linux futex in `rt/shim.c`; the macOS half is Saw).**

**Two of the migration's list entries needed no replacement at all, which is
what a name list can never tell you: `UnsafeMemory` is a struct of one `Int` and
DERIVES both markers, and `ReadOnly`/`WriteOnly` derive from the inner type that
is their only field. The interior-mutability EXEMPTION dissolved to nothing, as
the brief predicted. Original status: APPROVED + QUEUED (user, Aug 8 — direction
+ name in the morning round, D1/D2 ratified in the afternoon round). D1 = the
`UnsafeSync`/`UnsafeSend` declared markers with all three fences. D2 = the three
statics tiers, with the set-once half split out to `Once<T>` — PROMOTED into
this brief as unit 6 by the same round.**

## The gap

Interior mutability today is three compiler-known NAMES, consulted in three
different places: the 176b use-site exemption
(`statements.py` `_INTERIOR_MUTABLE_TYPES = {Atomic, SpinLock, UnsafeMemory}`),
the design-149 statics story (hints name `Atomic<Int>`/`SpinLock`; `Sync` by
FIAT for `Atomic`/`UnsafeMemory`), and the ABI guarantee `SpinLock._payload`'s
comment leans on ("a receiver carrying an `Atomic` cell arrives as the
caller's storage rather than as a copy" — `_self_by_pointer_for`, keyed on
Atomic containment). `SpinLock` itself proves the composition model works: it
is a plain std struct whose `&self -> &var T` crossing is library code confined
in an `unsafe` helper per design 130. But a library type that carries NO atomic
— a futex mutex, a OnceCell, a RefCell-analog, a payload slot in a lock-free
structure — has no way to ASK for the by-pointer receiver guarantee, and its
`&self` helper would silently address the callee's copy. The capability
exists; only the spelling is closed. The user wants it open: interior
mutability expressible by types the compiler does not know a-priori.

## Units

1. **The primitive.** `UnsafeMutableInterior<T>` in builtin.saw: an `unsafe
   struct` (the name satisfies 130's `Unsafe*` rule) holding an inline `T`,
   `NoCopy`, with ONE accessor — `func ptr(&self) unsafe -> UnsafePointer<T>`.
   That signature is the whole safety story: by design 130, every function
   touching the cell is dragged into the declared-unsafe domain with no new
   effect rules, and a safe public wrapper method takes on the all-safe-params
   soundness obligation exactly where `SpinLock.lock` already does. No other
   methods; construction wraps a `T` (`UnsafeMutableInterior(v)`).
2. **The structural property.** "Cell-carrying" = transitively contains an
   `UnsafeMutableInterior` field (Rust's internal `Freeze` analysis, inverted).
   Computed once per type, it drives FOUR compiler behaviors, replacing the
   name checks: (a) a receiver or borrow of a cell-carrying type ALWAYS
   travels by pointer — generalize `_self_by_pointer_for` from
   Atomic-containment; (b) a cell-carrying `static` never lands in a read-only
   segment (the 149 zero-init rule generalizes: an all-zero cell-carrying
   static still costs no image bytes); (c) codegen makes no
   shared-borrow-immutability assumptions across cell-carrying storage (audit
   what we emit today; the property must HOLD even if the current optimizer
   never exploited it); (d) structural `Sync` derivation is BLOCKED — a
   cell-carrying type is not `Sync` unless it says so (D1). `Send` stays
   structural (a cell moves fine; it is sharing that needs an argument).
3. **`UnsafeSync` / `UnsafeSend` — the thread-safety assertion (RATIFIED).**
   `Sync`/`Send` stay DERIVATION-ONLY — `extension X: Sync` remains rejected
   exactly per builtin.saw:203 (the draft's claim that `Send` had a declared
   precedent was wrong; nothing does). The assertion gets its own names: two
   new builtin marker traits, `trait UnsafeSync: Sync {}` and
   `trait UnsafeSend: Send {}` (the `Error: Printable` inheritance
   machinery), so a declared conformance satisfies every `T: Sync` /
   `T: Send` bound through the parent while generic code keeps its
   vocabulary. The `Unsafe` name carries the claim per 130's idiom — the
   conformance header IS the audited, greppable assertion, replacing every
   "`Sync` by fiat" comment. LEGALITY: declaring one is legal only where the
   structural derivation FAILED and every blocking field is unsafe-typed (a
   cell, `UnsafePointer`, `UnsafeMemory`) — you may hand-assert exactly what
   the unsafe domain already owns, never past a SAFE non-Sync field, which
   would be a claim about someone else's invariants. Conditional headers are
   supported and are half the point: `extension Mutex<T: Send>: UnsafeSync {}`.
   Three fences: (a) NOT boundable, NOT erasable — `T: UnsafeSync` and
   `any UnsafeSync` are errors hinting at `Sync`; the trait appears in
   exactly one position, the conformance header; (b) these are TWO BUILTIN
   traits, not a user-definable unsafe-trait feature — no 130
   name-enforcement extends to trait declarations; (c) the design-142 orphan
   rule applies unchanged. The error for a cell-carrying type crossing a
   task boundary without the conformance names the missing declaration AND
   the blocking field.
4. **Migrate the three, dissolve the list.** `Atomic<T>` holds
   `UnsafeMutableInterior<T>` (its four ops stay codegen-intercepted — the
   ATOMICITY is still intrinsic; only its interior-mutability stops being
   fiat) and declares `UnsafeSync`. `SpinLock.value` becomes
   `UnsafeMutableInterior<T>`; `_payload` becomes `self.value.ptr()` — the
   subtle `(&self.value) as UnsafePointer<T>` idiom retires — and its fiat
   migrates to a declared `extension SpinLock<T: Send>: UnsafeSync {}`.
   `UnsafeMemory` is NOT cell-carrying (it is a one-word address; mutation
   lands through the pointer, the indirection carve-out's territory); its
   fiat migrates to declarations under the same legality rule. The `Send`
   override list migrates in the same sweep: `Arc`/`Mutex`/`Channel`/
   `Task`/`SpinLock` plus the DF-182e container ruling (`Vector<T: Send>`,
   `Map`, `Set` conditional; `Data`/`StringBuilder` unconditional) all
   become declared `UnsafeSend` conformances, and `namespace.py:_send_sync`'s
   name list dissolves with the interior-mutability one. Then re-derive what remains of `_INTERIOR_MUTABLE_TYPES`:
   expected outcome is the set DISSOLVES (every blessed call is a `&self`
   method and never trips the `&var self` rule) — any residue that turns out
   to be load-bearing is kept per-case with a stated reason, not as a name
   list. The 176b rule itself DOES NOT MOVE: a wrapper's `&var self` methods
   stay uncallable through `&self`-reached storage — sibling fields are why —
   and the wrapper author's recourse is `&self` methods, which the cell is
   what makes writable.
5. **The proof: `Mutex` rebuilt inline.** Replace the heap
   `pthread_mutex_t` block with one inline cell-carried word — futex on Linux,
   `os_unfair_lock` on Darwin (`OS_UNFAIR_LOCK_INIT` is zero; futex convention
   is 0 = unlocked). Consequences, each stated in docs: a `static M: Mutex<T>`
   now WORKS with no initializer (zero-static, bss, matching SpinLock's
   story — the thing pthread's Darwin initializer, a nonzero sig word in
   `__DATA`, could never give us without baking macro bytes into the rt);
   `Deinit`'s destroy+free path disappears; movability is guaranteed by the
   Law of Exclusivity rather than an address-stability contract (any thread
   inside `lock()` holds a live `&self` borrow, and a move needs exclusivity —
   document that argument in the type's docs). `lock`/`try_lock` signatures
   and the blocking semantics are UNCHANGED (the thread-blocking contended
   path is preexisting, per the `mutex_lock_suspend` discipline — parity, not
   regression). Hosted only; freestanding Mutex stays out.
6. **`Once<T>` — the set-once static, the second proof (PROMOTED by the
   ratification round).** A small std type over this brief's own primitives:
   an `Atomic` state word + an `UnsafeMutableInterior<T>` payload slot,
   release-publish / acquire-read ordering INSIDE the type (the pairing a
   hand-rolled placeholder pattern silently gets wrong), and a declared
   `UnsafeSync` whose header bound is chosen in-unit so the sharing story is
   actually true for how the accessors move `T`. Semantics, pinned: zero =
   UNSET, so `static POOL: Once<UnsafePointer<UInt8>>` with no initializer
   is bss under the 149 rule; `set(v)` publishes once and a SECOND set
   PANICS (racing sets: compare-exchange, first wins, loser panics — two
   boot paths initializing is a program bug, not a condition); `get()`
   before initialization PANICS — both panics are the fault-not-status
   principle ratified in the 180 review (caller-checkable bug → panic,
   never a status); `try_get() -> T?` is the inspectable twin. Readers of a
   `Once<Config>` are SAFE functions — the unsafe domain around the old
   placeholder-then-assign pattern shrinks to the type's internals. This
   SPLITS the runtime tier of unit 7: set-once state is `static X: Once<T>`;
   `unsafe static var` remains only for state genuinely MUTATED under a
   serialization argument (the spec's TABLE/LIVE) — `var` means what it
   says again. The user's `unsafe static let` alternative was considered
   and declined WITH this as the replacement: a `let` you assign later
   bends the binding vocabulary, and the once-enforcement is dynamic
   either way — better carried by a named type than a hidden flag on a
   third static flavor.
7. **The statics tiers (RATIFIED).** A cell-carrying user static is legal
   at exactly three tiers: (a) ZERO-INIT — bare declaration, bss, design
   149's rule unchanged (the futex Mutex and an unset Once are both valid
   at zero by construction); (b) CONST-FOLDABLE MEMBERWISE construction —
   the initializer tree is synthesized/memberwise construction over
   const-foldable leaves (185's vocabulary), and the line is crisp: field
   aggregation folds, user `init` BODIES never run at compile time — a
   hand-written init with logic is rejected even where it visibly "would"
   fold, because folding bodies is const-fn and this brief refuses to back
   into it. Tier (b) ABSORBS DF-185b (filed by design 185, xfail-pinned by
   `examples/static_const_expr_init_xfail.saw`): design 41's
   `_is_const_init` is literals-only and separate from the evaluator, so
   even `static SIZE: Int = 4 * 1024` and the 185 brief's own
   `static RW: UInt8 = Perm.Read | Perm.Write` are refused today — widening
   it to the const-foldable tier needs the DF-172j pre-registration static
   pass to evaluate in DECLARATION ORDER with a cycle rule, which is this
   unit's work and flips that xfail. (c) runtime-computed initial state is
   NEVER a static initializer in any form — it is the placeholder-then-assign pattern:
   set-once wants `static X: Once<T>` (unit 6), mutated-throughout keeps
   `unsafe static var` + the author's ordering argument (149's discipline).
   No life-before-main, no static constructors, ever — a static is image
   bytes. A plain static must still be Sync, so a cell-carrying static
   needs its type's `UnsafeSync` declaration: units 3, 6 and 7 compose
   deliberately.
8. **Docs + tests.** Spec: rewrite the §3 interior-mutability paragraph
   around the property instead of the trio, the 149 statics section (the
   three tiers + the Once/unsafe-static-var split), the Sync/Send section
   (derivation-only stands; UnsafeSync/UnsafeSend are the declared markers);
   saw-lang skill: the wrapper idiom (cell field + `&self` methods + one
   small unsafe helper + declared UnsafeSync) and the set-once static idiom.
   Tests: the
   callee-copy regression a no-atomic cell-carrying type would have hit
   (by-pointer receiver proof); rodata/bss placement of cell-carrying statics
   (zero and const-init); Sync blocked structurally + unblocked by a declared
   UnsafeSync + the missing-declaration error naming the blocking field + the
   legality rejections (asserting past a safe non-Sync field; `T: UnsafeSync`
   bound; `any UnsafeSync`); a user-built Cell type end-to-end in a test (the
   "compiler never heard of it" proof); static Mutex + the Mutex concurrency
   set over TEN stable repeats (180 precedent); Once: double-set panic,
   get-before-set panic (both carrying `panic at FILE:LINE:`), cross-thread
   publish/read, zero-static bss placement, and the safe-reader proof (a
   `Once<Config>` consumer compiles with no `unsafe` anywhere); the 176b
   suite unchanged (wrapper `&var self` still rejected).

## Gates

Per-unit commits, full battery each (suite zero uncited xfails, lexdiff,
astdiff, Saw-irdet --all, bootstrap, gmgate, sos both arches). Unit 5 is the
scheduler-adjacent surface — ten-repeat stability on the new Mutex tests.
DF-186x findings as usual.

## Explicitly out

Safe `Cell`/`RefCell` std types (natural follow-ups, each ~a page of library
code over the cell — a later std design; `Once<T>` alone was promoted IN, as
unit 6); a field-level `interior` marker, a method-level marker, or an
`unsafe static let` binding flavor (each rejected in the design
conversation: they bless code, unsynchronized storage, or a hidden dynamic
flag rather than an auditable primitive); user-definable unsafe traits;
making the 176b CALL exemption transitive to wrappers (reintroduces the
sibling-field bug); freestanding/SOS Mutex; robust/priority-inheritance
mutex features; const-fn generality; a blocking/waiting `Once.get` (the
OnceLock wait — a panic is the v1 answer and the fault principle's).
