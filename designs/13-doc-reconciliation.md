# Design Brief 13 — Documentation reconciliation

**Source:** `todo_jul26.md` design concern 4 ("spec, README, and
implementation describe three languages") and priority item 5.
**Scope:** documentation only — `.md` files. NO changes under `sawc/`,
`examples/`, `test_runner.py`, or `Makefile`. The `designs/` directory is a
historical record — do not touch it. `todo_jul26.md` is current — leave it.
**Ground truth, in priority order:** (1) the implementation + the `examples/`
suite (240 passing tests enforce the real syntax/semantics), (2) the DECISION
sections of `designs/06`, `07`, `08` for the newly-decided semantics,
(3) the existing spec text for genuinely future features.

## Governing rules

- **Implementation wins on conflict.** Where the spec's syntax disagrees with
  what compiles (`pattern => expr` vs `case Pattern -> expr`; `some(42)`/
  `none` vs implicit wrapping + `None`; `!` as logical NOT vs `not`;
  `func magnitude(&self)` receiver forms vs what extensions actually use),
  rewrite the spec to the implemented form. Where the removed form is
  load-bearing history, one line "(earlier drafts used X; superseded)" at
  most.
- **Status markers, not deletion.** Never silently drop a spec-only feature.
  Every spec section gets a status tag: `**Status: implemented**`,
  `**Status: planned**` (designed, not built — e.g. dictionary literals,
  literal/range/guard match patterns, async/concurrency, Send/Sync), or
  `**Status: superseded**` (with what replaced it). Concise, consistent
  format at section top.
- **Every code example in a section marked implemented MUST compile and run
  with the current compiler.** Verify via scratch compiles
  (`.build/scratch/`, per CLAUDE.md workflow). Examples in planned sections
  should be marked as illustrative.
- Don't invent new features or semantics: where something is genuinely
  undecided (integer overflow, struct equality), say "unspecified — open
  question" rather than choosing.

## Files and what's stale in each

### LANGUAGE_SPEC.md (the main event)
Known drift to fix (critique + subsequent landings):
- Match syntax/patterns (see governing rule); exhaustiveness rules as
  implemented.
- Optionals: implicit wrapping + `None`; `!` force-unwrap; `not` is logical
  negation; fix the operator appendix.
- **Copy semantics**: delete the implicit-deep-copy-for-collections claim
  (`:437`-ish); write the Copy trait family section from `designs/06`'s
  DECISION (Copy umbrella, ImplicitCopy cheap contract, ExplicitCopy
  expensive contract + move-required + `.copy()`, NoCopy, auto-Copy for
  trivial types, `T: Copy` bound, containment rules, derivation).
- **String**: brief 11 updated the string section — review it fits the new
  structure, ensure the atomic-ordering note and byte-string status are
  there, and that `len()`/immutable-buffer/`+`-allocates semantics are
  stated. UTF-8 validation is *planned* (fromBytes/literal validation not
  yet implemented).
- **References/exclusivity**: brief 10 added evaluation order + the law of
  exclusivity — integrate properly (status: implemented), including the
  no-escape invariant constraints on future features.
- Resource traits: `Deinit` semantics as implemented (LIFO scope cleanup,
  no manual deinit calls), renamed `ImplicitCopy` everywhere `CustomCopy`
  appears.
- Runtime semantics now real: div-by-zero panics (`/`, `%`), constant
  array-index bounds errors, tuple-index bounds. Integer overflow remains
  unspecified — mark as open.
- Generics: monomorphization, trait bounds, bounded extensions
  (`extension Vector<T: Copy>`), abstract checking of generic bodies with
  its documented deferrals (return-type reconciliation, bound-aware method
  resolution) — describe honestly.
- Compiler flags worth a short section: `-O0`/default O1, `--emit-ir`
  (note its builtins limitation), `-v`.

### README.md
Update the pitch claims to what's now true: memory safety ENFORCED
(value-transfer checkpoint), law of exclusivity, Copy trait family (the
"copy by default" framing needs rewording — trivial types copy, owning
types move with explicit `.copy()`), refcounted String. Feature list and
any example code must compile.

### CLAUDE.md
- "Key Design Decisions": rewrite the Memory Management bullets to the Copy
  family reality; `CustomCopy` → `ImplicitCopy` anywhere it appears.
- "Current Features": add Copy family, exclusivity check, String model,
  div-by-zero panic, bounds checks, `-O0`, bounded extensions.
- Example snippets must compile.
- Test-count line: state the count is ~240 and growing; better, phrase it
  without a hard number so it doesn't rot ("see `make test`").
- Do NOT touch the Python Environment / Scratch / Command Hygiene sections.

### TESTING.md
Stale tallies ("197 total", "1 xfail" examples) — reword counts to be
non-rotting where possible; verify directive documentation still matches
the runner (multi-pattern `-f`, `-v` xfail detail are documented; XPASS
semantics unchanged).

### TODO.md and other stray .md (blade_todo.md, pm_todo.md,
package_manager_design.md, sawc/*/README.md)
Read each; fix only what is WRONG (landed items still listed as todo, old
trait names, dead syntax in examples). Don't rewrite roadmaps or reorganize
someone's planning docs — surgical corrections + a dated "landed" note
where a whole section is done. `sawc/codegen/README.md` and
`sawc/typechecker/README.md` were partially updated by earlier briefs —
check they mention `_expr_type`/`mangle.py`/checkpoint accurately.

## Report back
Per file: what was wrong → what it says now (summary, not diffs). The full
list of sections tagged planned/superseded. Every doc example you compiled
(count) and any that COULDN'T compile plus how you resolved it (fixed the
example vs discovered a real doc-vs-impl mismatch worth flagging). Anything
you found that looked like a genuine open design question — list, don't
decide. Non-allowlisted commands used (ideally none).
