# Design 186 — `UnsafeMutableInterior<T>`: interior mutability without the name list

**Status: DRAFT (Aug 8). Direction + type name approved by the user ("i like
the proposal", `UnsafeMutableInterior<T>`). Two decisions below (D1 Sync
surface, D2 statics fence) are PROPOSED, not ratified — settle both before
this queues. Sequencing: after the current wave (158/182/185) and the net
track; touches typechecker + codegen + builtin.saw + std, so nothing else on
those surfaces runs beside it.**

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
3. **D1 (PROPOSED — needs ratification): explicit `Sync` conformance.** A
   cell-carrying type may declare `extension T: Sync {}`, and that declaration
   is the author's audited assertion that the type synchronizes its own
   interior (lock protocol, atomicity) — the same declared-conformance shape
   `Send` already has, and the principled replacement for today's "`Sync` by
   fiat (the Atomic precedent)" comments. The conformance is only legal on a
   cell-carrying type (on anything else it is derivable or impossible), and
   the error for a cell-carrying type crossing threads without it names the
   missing declaration. Alternative if ratification wants more ceremony: gate
   the declaration behind an attribute; the recommendation is the bare
   conformance — the cell in the field list is already the audit trail.
4. **Migrate the three, dissolve the list.** `Atomic<T>` holds
   `UnsafeMutableInterior<T>` (its four ops stay codegen-intercepted — the
   ATOMICITY is still intrinsic; only its interior-mutability stops being
   fiat) and declares `Sync`. `SpinLock.value` becomes
   `UnsafeMutableInterior<T>`; `_payload` becomes `self.value.ptr()` — the
   subtle `(&self.value) as UnsafePointer<T>` idiom retires. `UnsafeMemory` is
   NOT cell-carrying (it is a one-word address; mutation lands through the
   pointer, the indirection carve-out's territory) and keeps `Sync` by
   declaration. Then re-derive what remains of `_INTERIOR_MUTABLE_TYPES`:
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
6. **D2 (PROPOSED — needs ratification): the statics fence.** v1
   cell-carrying user statics are legal when zero-init (already design 149's
   rule) or when the initializer tree is const-foldable end-to-end (185's
   const-eval does the arithmetic); anything runtime-computed still needs
   `unsafe static var`. This keeps "a static is image bytes" true and defers
   const-init generality to a real const-fn design.
7. **Docs + tests.** Spec: rewrite the §3 interior-mutability paragraph
   around the property instead of the trio, the 149 statics section, the
   Sync/Send section for D1; saw-lang skill: the wrapper idiom (cell field +
   `&self` methods + one small unsafe helper + explicit Sync). Tests: the
   callee-copy regression a no-atomic cell-carrying type would have hit
   (by-pointer receiver proof); rodata/bss placement of cell-carrying statics
   (zero and const-init); Sync blocked structurally + unblocked by
   declaration + the missing-declaration error text; a user-built Cell type
   end-to-end in a test (the "compiler never heard of it" proof); static
   Mutex + the Mutex concurrency set over TEN stable repeats (180 precedent);
   the 176b suite unchanged (wrapper `&var self` still rejected).

## Gates

Per-unit commits, full battery each (suite zero uncited xfails, lexdiff,
astdiff, Saw-irdet --all, bootstrap, gmgate, sos both arches). Unit 5 is the
scheduler-adjacent surface — ten-repeat stability on the new Mutex tests.
DF-186x findings as usual.

## Explicitly out

Safe `Cell`/`RefCell`/`OnceCell` std types (natural follow-ups, each ~a page
of library code over the cell — a later std design); a field-level `interior`
marker or method-level marker (rejected in the design conversation: blesses
code or unsynchronized storage rather than an auditable primitive); making
the 176b CALL exemption transitive to wrappers (reintroduces the
sibling-field bug); freestanding/SOS Mutex; robust/priority-inheritance
mutex features; const-fn generality.
