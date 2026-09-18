# Design 274 — Reconciling design 259 with the prototype parser track

**Status: DRAFT Sep 17 2026** (lead), for the user's review. Tracker: SL-2
(the design-259 umbrella) carries this brief; SL-300 is the prototype epic
it re-homes 259's selfhost-side units onto. Nothing here re-opens a ruling:
design 259 §0 (the freeze doctrine), §3 (R1–R8, R7′) and §7 (the bootstrap
endgame) stand verbatim. What this brief does is replace 259 §1 and §5 —
the ladder position and the unit map — with what is true on Sep 17, and
turn 259's finding roster into tracker actions.

## 0. Why now

Design 259 was authored Sep 1 for a parser port written against Box-linked
enums under `selfhost/parser/`, with the Python parser's grammar debt (U0)
and depth funnel (U1) fixed FIRST so the frozen surface would be clean.
Three things happened since, none of them in the brief:

1. **The user's Sep 10 arena/index ruling** replaced Box-linked storage with
   an append-only arena of flat nodes plus a child-index vector, executable
   under the mini-VM (recorded in `prototypes/minivm/M18_AST.md`).
2. **The prototype track built the parser 259 describes** — M18 (SL-301,
   the arena AST + a function/expression subset), M19 (SL-302, the canonical
   renderer + the 2,696-file inventory + the corpus differential), M20
   (SL-303, name assignment + the inventory resolved) — under
   `prototypes/parser/`, with the canonical `sawc/ast_dump.py` bytes as its
   oracle and NO divergence ledger, exactly as §0 demands.
3. **The Python side did not move.** Probed Sep 17 against main: 300 nested
   parentheses is still a raw `RecursionError` traceback (R4/U1 never
   landed); a bare `return` arm is still `Unexpected token: RETURN` (R7′
   never landed); every Class-1 issue is open. The prototype meanwhile
   implements the RULED behavior — R3's operator-newline continuation and
   R4's depth 256 are in M18 — so the differential already cannot compare
   exactly the shapes the rulings cover, and every grammar slice widens
   that set. M20's own doc lists "design 259 pre-freeze obligations" as
   deferred, unowned work. This brief owns them.

## 1. Unit reconciliation

| 259 unit | disposition | where it lives now |
|---|---|---|
| U0 grammar debt (Python) | **STANDS, urgent** — §3 below | this brief's U0′, a compiler dispatch |
| U1 depth funnel (Python) | **STANDS, urgent** — folded into U0′ | this brief's U0′ |
| U2 AST in Saw, Box-linked | **SUPERSEDED** by the Sep-10 arena ruling | landed as M18 (SL-301) |
| U3 the parser + `parsediff` | **RE-HOMED**: the prototype parser grows slice by slice, measured by the inventory; `compare_examples.py` is `parsediff` in embryo | SL-300 children (M21+) |
| U4 differential fuzzing | **DEFERRED as a scheduling choice, not a technical one** — the M19 harness already embeds arbitrary source batches and captures every verdict, so sawfuzz's mutants can be fed through it today | SL-300, sequenced after M21 (§3 U4′) |
| U5 battery lanes | **OWED NOW** — nothing gates `prototypes/parser/` today | this brief's U5′ |
| §4 N10 soundness | **CLOSED** — probed Sep 17: `let w = v as Vector<Int>` is refused cleanly (the ownership epic's units A/B closed the mechanism) | close at SL-2's next filing |
| §4 Class-2 hard four (SL-62, SL-63, SL-47, SL-36) | **NO LONGER PREREQUISITES** — an arena has no Box-linked enums, no `Box<T>?` child, no lend into a payload | ordinary backlog bugs |
| SL-142 CBOR binary-AST seam | **DEFERRED** to the file-reading milestone: a seam matters when the AST crosses a process boundary, which it does not yet | SL-300, with the CLI unit |
| SL-143 lexer-pilot remainder | **MOOT** — SL-242 (M16, SL-259/260) is the lexer's acceptance; close with a pointer | close |

## 2. The findings ledger, reconciled against the live tracker

259 §2 was written before sawtracker; its DF numbers map to SL issues and
its N numbers were never filed. Verified Sep 17 (tracker search + probes):

### 2a. Class 1 — ossifies into the contract

| 259 row | tracker | status Sep 17 | ruling |
|---|---|---|---|
| DF-284b `{ … }()` and the general postfix call | SL-73 | OPEN; M18's audit widened it: `(f)(1)`, `factory()(1)`, `(1)(2)` all silently drop the call | R1 |
| DF-266a leading `-` tail after a closed block | SL-45 | OPEN | R2 |
| DF-172d operator-newline continuation | SL-83 | OPEN; the prototype implements R3, so its `x = g(…) +⏎ 2` fixture is oracle-blind | R3 (ruled) |
| DF-259c trailing closure in a `try` operand | SL-41 | OPEN, pinned XFAIL | mechanism-known fix |
| DF-259b reserved word in five decl-name slots | SL-40 | OPEN, diagnostic-only | U0′ cheap batch |
| DF-215j `return` in a value arm | SL-59 | OPEN | dissolves under R7′ |
| DF-215i boolean `guard cond else` | SL-58 | OPEN, **ruling owed** | — |
| DF-276a unrepresentable float literal | SL-68 | OPEN, silent wrong answer | mechanism-known fix |
| N1 parser recursion unguarded | **unfiled** | OPEN, reproduced Sep 17 (traceback at 300 parens) | R4 (ruled) |
| N2 `as Int??` whitespace picks the target | **unfiled** | OPEN (not re-probed) | R5 |
| N3 bare trailing closure on a free function | **unfiled** | OPEN (not re-probed) | R6 |
| N4 `lend` statement-only in an arm | **unfiled** | dissolves under R7′ with SL-59 | R7′ (ruled) |
| N5 unclosed `{` anchored at the next `func` | **unfiled** | OPEN; the POSITION freezes, so this is contract damage | U0′ |
| N6 `.5` message, N7 unterminated string at EOF | **unfiled** | OPEN, diagnostic-only | U0′ cheap batch |
| N8 labelled call parses as `StructInit` | **unfiled** | bless as-is | R8 (ruled) |
| **B1 (NEW, M20)** Python accepts `x = 1 y` and `let x = 1 y` as two statements on one line | **unfiled** | reproduced Sep 17; LANGUAGE_SPEC line 56: "A statement ends at the end of its line. There are no semicolons." — so this is a silent misparse, not a grammar choice | **RULING OWED**: recommend REFUSE at the second statement's first token, which is what the prototype already does (`expected statement boundary`) |

### 2b. Class 2 and the rest

- N9 (dependency-position prelude collision) rides SL-71 (DF-280b).
- N11/N12 (bare SIGSEGV on stack exhaustion, Saw-level and drop-chain) —
  **unfiled**; they are why R4's limit must be enforced by the parser. File
  as one runtime issue; not a parser unit.
- N10 — CLOSED (above). DF-273a — the non-reproducer; never filed; drop.
- Class-2 list (SL-62, SL-63, SL-47, SL-36, SL-61, SL-26, SL-28, SL-48,
  SL-53, SL-74, SL-75): all OPEN, all ordinary backlog now that the port
  is not written in Box-linked enums. The prototype track is the ruled
  prioritization oracle (SL-242, Sep 10): a Class-2 bug the prototype's
  own source hits gets fixed; the tail waits.

## 3. Units

- **U0′ — the Python grammar debt + depth funnel (ONE compiler dispatch).**
  R1 (SL-73, incl. the M18-widened postfix faces), R2 (SL-45), R3 (SL-83),
  R5 (N2, under "spelling never depends on whitespace"), R6 (N3), R7′
  (SL-59 + N4; arm body = `block | statement`, pins per 259 §3), R8 (N8:
  document the blessing in `docs/AST_DUMP.md`), N5's anchor, DF-276a
  (SL-68), DF-259c (SL-41), the cheap diagnostic batch (SL-40, N6, N7),
  B1 (once ruled), and R4 (N1: one wrapper counting every recursive-descent
  entry point, `nesting exceeds the parser depth limit (256)` at the
  opener, pins at 256/257 that MIRROR `prototypes/parser`'s, sawfuzz's
  oracle restored). Obligation 1: the depth wrapper is a funnel with named
  entries. Obligation 3 does not apply (no safety guarantee). **Gate**: the
  per-commit compiler gate, plus the prototype's own harness as a SECOND
  oracle — `test_canonical.py --debt-probe` must flip GREEN, and every
  fixture in `fixtures/canonical_cases.json` marked `python_oracle: false`
  for a Python-side reason (the R3 fixture) flips to `true` in the same
  landing. That is the concrete meaning of "the prototype is the
  prioritization oracle". Serializes with the compiler queue (after the
  SL-280 → SL-274 pair, before M21 widens the gap with `if`, which hits R2
  and N1 at 48 nested blocks).
- **U5′ — the `parser` battery lane (tooling, can ride with U0′).** A
  STAGES entry building minivm into `.build/minivm-battery/` (the `minivm`
  lane already does) and running the M19/M20 commands: the harness
  unittests, `inventory.py --check`, `test_parser.py`, `test_canonical.py`,
  `compare_examples.py`. The snapshot hashes every example, so any gate
  that asserts its freshness makes every examples/-touching patch
  regenerate it — and that assertion is NOT only `--check`: two of the
  harness unittests (`test_checked_in_inventory_is_sorted_complete_and_hashed`,
  `test_checked_in_inventory_has_no_classification_drift`) assert the same
  thing, so demoting `--check` alone changes nothing. The choice is
  therefore binary, and it is a **ruling owed**:
  (a) **CHURN** — the lane gates on freshness (unittests + `--check`), and
  every patch that adds or edits an example regenerates
  `examples_inventory.{json,md}` as part of its own diff (a one-command
  step, `inventory.py`, documented in TESTING.md beside the XFAIL policy;
  the 2,698-line JSON lands in every such patch); or
  (b) **SPLIT** — the two snapshot unittests move to their own module
  (`tests/test_snapshot.py`) which the lane runs REPORT-ONLY together with
  `--check`, while the remaining unittests, the arena/canonical gates and
  the differential GATE; the snapshot is regenerated by convention at the
  start of each parser milestone, and a stale snapshot is visible in the
  battery log but blocks nothing. The differential reclassifies fresh on
  every run, so under (b) nothing a stale snapshot could hide reaches the
  gate. Lead recommends (b).
- **U2′–U4′ — the prototype track (SL-300 children, codex's lane, one
  milestone per patch, lead-reviewed).** In order: M21 control flow with
  an explicit continuation/block stack (M20's doc names it as the
  precondition for `if`); the canonical-schema decision for a general
  callee (today a located renderer refusal; a ruling, not a fix); **U4′
  differential fuzzing**, which needs no file I/O — `test_canonical.py`'s
  `run_vm_canonical_cases` already embeds arbitrary source batches and
  returns every verdict, so sawfuzz's mutated corpus feeds both parsers
  through the existing harness with the agree-on-verdict oracle of 259 U4;
  it is sequenced after M21 only because mutants of a grammar this small
  mostly land in refusals, not because anything blocks it; the file-reading
  CLI (which is when SL-142's CBOR seam becomes writable); then the
  design-259 port proper — the standalone parser over the whole corpus.
  **Full-corpus acceptance is TWO parities, not one.** `compare_examples`
  today compares ACCEPTED files only — a Python-rejected file (95 today)
  is classified `parse_error` and never reaches the prototype. Design 259
  §0 froze rejections too: verdict + `line:col` parity on the first error,
  message prose free. So `parsediff` = `compare_examples` extended with a
  REJECTION lane: every `parse_error` row is also fed to the prototype,
  and the run fails unless the prototype rejects at the SAME `line:col`
  (`ERROR` record parity); a file one side accepts and the other rejects
  is a mismatch, never an exclusion. Acceptance = 2,696 of 2,696 across
  BOTH lanes, with the counts reported separately. The bar never changes:
  byte parity or position parity, or a ruling that fixes Python and the
  corpus; never a ledger.

## 4. Rulings owed (user)

1. **B1** — refuse `x = 1 y` at the second statement (recommended), or
   document the permissiveness and make the prototype match it.
2. **U5′** — (a) CHURN or (b) SPLIT for the inventory snapshot's
   freshness assertions (lead recommends (b)).
3. DF-215i (SL-58) — boolean guard, still open from 259.
4. N2's grammar detail under R5 — U0′ designs it; the user rules on the
   result if `as Int??` gains a meaning.

## 5. Tracker actions at approval (lead)

File as SL issues, each citing this brief: N1 (R4, with the Sep-17
traceback), N2, N3, N5, N6+N7 (one diagnostic issue), N11+N12 (one runtime
issue), B1. Close N10 on SL-2 with the Sep-17 probe. Update SL-2 to point
here and re-stage it QUEUED; SL-143 closes with a pointer to SL-242. The
todo.md `[QUEUE]` pointer for design 259 becomes this brief's.
