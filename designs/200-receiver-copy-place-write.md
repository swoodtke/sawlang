# Design 200 — the receiver-copy place write is an error

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
