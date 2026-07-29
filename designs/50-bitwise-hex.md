# Design Brief 50 — T1a: bitwise operators + hex/binary literals

**Source:** path-to-applications Tier 1 (T1a). Table stakes for
systems code; design 46's own UART example needs `&`. No decision
required — the spec's operator appendix has always listed these.

## Items
1. **Integer literals:** `0xFF`, `0b1010` (and `0o755` octal — include
   for completeness), underscore separators (`0xDEAD_BEEF`,
   `1_000_000`) in all integer literal forms. Lexer + range checks
   per target width (design 47 interplay: if 47 has landed, width
   checks use the platform rule; else current 64-bit — note which).
2. **Binary bitwise operators** `& | ^` and shifts `<< >>` on integer
   types only: parser precedence per the spec appendix (C-family:
   shifts above comparisons; `&` above `^` above `|`; document the
   exact tiers in the spec — and NOTE: `&` the binary operator must
   coexist with unary reference `&x`, call-site `&var`, and the
   `&+ &- &*` wrap tokens; the lexer/parser disambiguation is the
   careful bit — binary-operator position vs prefix position; add a
   mixed-expression test like the brief-31/34 ones).
3. **Unary `~` complement** (integer only).
4. **Compound assignments** `&= |= ^= <<= >>=` (the spec appendix
   lists them; compound machinery exists from brief 31's checked +=).
5. **Shift semantics decided here (small, no user input needed —
   follow the checked-arithmetic house rule):** shift amount >= bit
   width or negative PANICS ("shift out of range" — matching the
   overflow-panic family; Rust debug precedent); `>>` is arithmetic on
   signed, logical on unsigned. Document in spec. Wrapping-shift
   variants NOT shipped (add later if kernels demand).
6. **Tests:** literal forms + range errors; each operator on
   signed/unsigned incl. boundary patterns; precedence assertions
   (`a | b & c`, `x << 2 + 1` — spell expected parse in tests);
   shift-out-of-range panics; `~`; compound forms; the
   ref/wrap-token coexistence test; a register-mask idiom test
   (`(v & ~MASK) | (bits << SHIFT)`).
7. **Docs:** spec operator appendix marked implemented with the
   precedence table; CLAUDE.md operators line.

## Hazards
The `&` lexing tangle (four meanings: binary AND, reference-taking,
`&var`, wrap-ops). Existing suites (exclusivity, wrap ops, references)
are the oracle — any regression there is a disambiguation bug. Full
suite per commit; zero xfails end state.
