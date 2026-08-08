# Design 187 — the coroutine fix batch (+ the 182 completion)

**Status: APPROVED + QUEUED (user, Aug 8: "yeah, let's do that, queue it").
DO NOT DISPATCH until the user resumes the queue — the standing order is
STOP after design 183 integrates. One agent, one brief: every unit below
shares the coro_transform / optional-lowering / std.process surface, which
is exactly why the pile accumulated instead of landing piecemeal. Units 1-2
are SOS-M2 blockers and lead. All findings are FILED with repros; four
carry xfail pins whose XPASS flips are the acceptance tests.**

## Unit order

1. **DF-158e — the freestanding embedding miscompile (SOS-M2 BLOCKER).**
   `object_only` decides `is_entry`, `is_entry` records a suspending `main`
   as a coroutine root, and without it the closure walk never reaches a
   spawn root's nested suspending callees — the call lowers as a direct
   BLOCKING call. In a kernel the nested park runs inline. Fix the root
   collection so `-c`/freestanding embeds exactly what a hosted build
   embeds; regression test at the IR level (frame symbol present under
   `-c` — a tools/ harness check is fine, the examples suite cannot spawn
   under `-c`), and `sos/tests/taskdump.saw` grows past one frame deep,
   which is the honest proof.
2. **DF-158c — `@export` return width swapped on 32-bit targets.**
   `-> Int64` emits `i32` on riscv32 and `-> Int` emits `i64`; the
   `--runtime-provider` check compares Saw types and cannot see it.
   Codegen fix + an IR-level cross-compile width test; unblocks the
   riscv32 task dump (drop the arm64-only filter on the SOS `taskdump`
   case when it passes).
3. **DF-158a — `Never` in result position of a suspending body.** A
   diverging `panic` as the tail (or `return panic(...)`) stores a
   nonexistent value into `__result` and ICEs. `Never` emits no store —
   the frame is dead there. Flips `coro_panic_value_position_xfail`.
4. **DF-158b — a suspending call in a `Void` body's tail.** The tail of a
   `Void` body has nothing to store, so it lowers exactly as a statement
   would, instead of being rejected with a message about a shape the
   author never wrote. Flips `coro_tail_suspend_void_xfail`.
5. **DF-158d — nested `yield_now()` is a silent no-op.** The documented
   escape hatch ("put a `yield_now` in the helper") does nothing: the
   callee gets no frame, the yield runs outside one, the task never cedes.
   Same effect-edge family design 96 closed for std METHOD calls, never
   closed for the design-114 wrapper. Fix so a callee reaching the yield
   intrinsic embeds; test with a probe that COUNTS cedes (no interleaving
   assertions — the standing rule).
6. **DF-174g — multi-wrap into a nested optional slot.** One `_fit_optional_slot`
   wrap leaves an `Int?` in an `Int??` cell (first peel works, second
   crashes exit 133; three layers ICE). The gap is the wrap/peel PAIR, not
   the store — a recursive fit alone was tried and does not fix it (probes
   under `.build/scratch/p174*`). Promote the probes to examples when
   fixed.
7. **DF-174h — `??` default one layer too deep is accepted.** On
   `Vector<Int?>`, `v.get(9) ?? v.get(0)` should be a clean type error
   (the default owes the PEELED type, `Int?`) and instead emits invalid
   IR. Typechecker fix; the IR error is only the symptom.
8. **DF-182e — the ruled `Send` additions.** Per the Aug-8 ruling: owning
   containers are `Send` iff contents are — `Vector<T: Send>`,
   `Map<K: Send, V: Send>`, `Set<T: Send>` conditional; `Data` and
   `StringBuilder` unconditional by `String`'s argument — as additions to
   `namespace.py:_send_sync`'s override list, explicitly INTERIM: design
   186's migration sweep converts the whole list to declared `UnsafeSend`
   conformances. Positive tests (each container held across a suspend in
   `TaskGroup(threads: 2)`) and the negative (a non-Send element type
   still refuses).
9. **DF-182c — the dispatch's payload store becomes a MOVE.** An
   `if let`/`guard let` over a `move` scrutinee spanning a suspension:
   the drop-flag-clear ordering is already known to hold (tried and
   recorded); what remains is the store of the unwrapped payload into the
   frame field, which is a copy a NoCopy payload refuses and an
   ExplicitCopy one would double-drop. This is the reviewed surgery slot.
   Flips `coro_move_scrutinee_span_xfail`.
10. **`Command.output()` goes cooperative — DF-181a fully closes.** Two
    lines on `run()`'s park loop once units 8-9 hold (irdet's shape needs
    both). Flips `process_output_starvation_xfail`; the deprecated
    `__saw_rt_proc_wait` drains to zero callers and is REMOVED (rt/ABI.md
    updated — the drain note already promises this). The design-182
    ten-repeat stability standard applies to the new concurrency tests.

## Gates

Per-unit commits, full suite green each, zero uncited xfails; the five
pins above flip XPASS in their fixing commits. Final battery: suite,
lexdiff, astdiff, Saw-irdet --all (mangling untouched, but the optional
lowering changes IR — byte-identity across the corpus is the check),
bootstrap, gmgate, sos_runner both arches (the riscv32 taskdump case
un-filtered by unit 2). Ten repeats on every new scheduler-surface test.
DF-187x findings as usual.

## Explicitly out

The `UnsafeSend` conformance surface itself (186 owns it); any offload
work (183/184); `Command.kill`; const-fn; the DF-146k `shared borrows`
item (separate ruling pending).
