# Design 200 — the receiver-copy place write is an error

**Status: LANDED Aug 10** — three units, tracked battery green, DF-176c
closed. What the units settled beyond the brief's text is recorded at
the bottom.

**Status: RULED + AUTHORED Aug 10 (morning review), ready to queue.
Closes DF-176c — the LAST surviving member of the vanishing-write
family (every sibling became a compile error in designs 176/188). The
ruling has two halves: (1) a plain `&self` method writing receiver
storage through a PLACE WINDOW on an inline field (`self.grid[0] += 100`
where `grid` is inline and its type has a `borrows` accessor) is the
same "a `&self` method may not write its receiver" error design 176
gives the direct spelling — today it is a silent no-op into the
callee's by-value copy; (2) the `borrows`-BODY half is CORRECT AS-IS
and is hereby documented as intended — an accessor's receiver travels
by pointer, so a prologue/epilogue place write there lands, gated by
`#lend_var` in the shared specialization exactly as design 179 built
it. The fix site is the place lowering (`place_uses._window_call`, the
`place_lowered` marker), NOT `_reject_var_self_call_on_shared_self` —
judging the synthesized call by the method rule would name a method the
source never wrote and would reject `lend self.inner[i]`, design 175's
legitimate forwarding.**

## Units

1. **Conformance rows first (obligation 3).** M-family rows: the
   DF-176c repro (reject — plain `&self`, inline field, window write);
   the same write on a HEAP-reaching field (`self.rows[0].push(9)` —
   accept, the copy shares the buffer, the existing carve-out); the
   borrows-body prologue write (accept, by-pointer receiver); the
   `#lend_var`-gated write in a flavored accessor (accept, exclusive
   specialization only); `&var self` method with the same window write
   (accept).
2. **The check.** In the place lowering: a synthesized window call
   whose root is an INLINE field of a `&self` receiver, in a plain
   (non-borrows) method body, opening an EXCLUSIVE window → the
   design-176 receiver-write error, anchored at the write, hint naming
   `&var self` and `borrows`. Shared (read) windows stay legal. The
   inline-vs-indirect test is the one design 176 already uses for the
   direct spelling — reuse it, do not re-derive it.
3. **Pins + docs.** The two `.build/scratch` probes from the finding
   become the conformance rows (unit 1 already landed them); spec
   design-176 section gains the window spelling; skill's "&self MAY
   NOT WRITE ITS RECEIVER" gotcha gains one sentence naming the place
   spelling.

## Gates

Per-unit commits, tracked battery each; irdet --all. Consumer sweep is
the suite plus a grep for exclusive windows on inline fields in `&self`
methods across std (expect zero — std's containers reach storage
through heap indirection, which is the carve-out).

## Explicitly out

Any change to borrows-body semantics or `#lend_var` (half 2 ratifies
the status quo); the design-175 composition pessimization note
(documented, stands); DF-188j (design 199).

## What the units settled

**The inline-vs-indirect test could not be reused as-is.** The brief said
"reuse design 176's test, do not re-derive it", and the reuse turned out
to need one new input. Both the refusal and the carve-out spell
`self.<field>` at the window's receiver — `self.grid` and `self.rows`
are each an inline field by `_self_storage_type` — so the receiver walk
alone answers alike for both. What separates them is where the ACCESSOR
lends from, a property of its declaration: `Grid.[]` lends an element of
its own `[Cell; N]`, `Vector.[]` lends out of the heap buffer
`self.buffer` points at. So `place_transform` (which already
distinguishes the two, in `_check_rooted_in_receiver`) records each
lending path's SHAPE — `(('member', 'cells'), ('index',))` — and
`place_uses` walks the chain against the receiver's real type. Design
176's walk is reused and EXTENDED by one hop: a place continues it
exactly when the accessor it names lends inline itself. That makes
`self.rows[0][0]` stop at the `Vector` and makes design 175's
`lend self.inner[i]` forwarding record nothing inline, which is the
brief's constraint arriving as a consequence rather than a special case.

**The matrix, not just the repro.** M31 grew to seven rows once the walk
existed, because the rule quantifies over "storage inside the receiver"
and each hop is a position: a field, a nested field, a tuple element, an
optional payload, an inline-array element, an enum payload lent out of a
`match` arm, and the non-assignment door (a `&var self` method on the
lent element, which enters the funnel through `_chain_window` rather
than `_assignment`). Two of those did not work on the first cut — the
enum payload, because a field's declared type reaches the lowering as
the parser left it and an enum name defaults to STRUCT kind.

**Consumer sweep: zero.** No exclusive window on an inline field in a
`&self` method exists in std, blade, libs, sos or devtools. Two greps
over all five — `self.<field>[...] =` for the write form and
`self.<field>[...].<method>(` for the call form — return fifteen hits and
not one is a place. `FixedBuf.set` writes a plain `[Int8; N]` from a
`&var self` method; twelve are `UnsafePointer` derefs (`self.ptr[0]`,
`self.group_ptr[0]`, `self.result_ptr[0]`), which are not accessors at
all; `libs/toml` reaches a `Vector` element, the documented indirection
carve-out. The full suite, irdet over the whole corpus, the bootstrap
and the SOS boot all confirm it: the refusal landed without changing any
existing program.

**One finding filed: DF-200a.** The `&var self.<field>` PROJECTION rule
reads its lvalue syntactically (`_projects_from_self`), so it refuses
`f(&var self.rows[0][2])` where the assignment rule — which walks types
— accepts `self.rows[0][2] = 55`. One storage, two answers. It is
conservative (a refusal, never a silent write) and aligning them relaxes
a safety refusal, so it wants a ruling rather than a drive-by fix; the
M32 header names it.
