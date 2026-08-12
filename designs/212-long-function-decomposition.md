# Design 212 — long-function decomposition sweep

**Status: RULED Aug 12 (user: locate + refactor, "mostly mechanical")
+ AUTHORED; dispatches to a Sonnet agent as a mechanical pass.**

## Motivation

Saw has no local references: `let r = &foo.bar.baz.arr` is not a
binding form, so a long function re-spells its deep accessor chains at
every use. The idiom that fixes it is EXTRACTION — a helper that takes
the inner place by reference (`func f(arr: &var Vector<T>)`, called as
`f(&var foo.bar.baz.arr)`) so the chain is spelled once at the call
site and the helper works through the reference. An Aug-12 review
sweep of the 70 maintained `.saw` files (blade, libs, sawc/std,
sawc/rt, devtools, sos — test corpora excluded) found the repeated-
chain smell concentrated in two hot spots (the taskgroup executor
internals and blade), plus a handful of plain copy-paste duplications
that want ordinary extraction, and one enum-idiom miss.

## Rules of engagement

- **Pure refactor. ZERO behavior change.** No public API changes: every
  new helper is module-private (and `__`-prefixed where it sits beside
  the existing `__saw_*` executor internals). No signature, semantics,
  or diagnostic change to anything exported.
- Full suite green per commit; one unit per commit.
- A helper whose signature names an unsafe type (`UnsafePointer<T>`)
  is declared `unsafe` in the post-parameter effect slot (design
  130/136) — expected and correct for the taskgroup unit.
- **sos/ is OUT OF SCOPE** (its own review gate; the sos candidates
  were nits anyway).
- No XFAIL additions. If a refactor exposes language pain — e.g. a
  place that SHOULD pass by reference but can't — STOP that unit,
  record a DF-finding in the tracker, and move on (no workarounds).
- Obligations check (design 190): no position-quantified rule (ob 1
  n/a); no behavioral contract flips — helpers are new private
  symbols, all existing call sites keep identical observable behavior,
  and the `bench` stage's checksums plus `bootstrap` gate that claim
  (ob 2); no safety surface touched (ob 3 n/a).

## Units

0. **Brief + tracker.** Commit this brief and a one-line entry in
   `designs/todo.md`'s queue.
1. **taskgroup executor helpers** (`sawc/std/taskgroup.saw`). The
   file has ~93 occurrences of `g[0].<field>` (`g` is the
   `UnsafePointer<TaskGroup>` from the spawn boundary), concentrated
   in `__saw_exec_worker` (:695, ~175 lines), `__saw_exec_run`
   (:1318, ~112 lines), `__saw_bt_dump` (:1741). Extract helpers
   taking `g` — at minimum a slot-state snapshot (the repeated
   done/active/remaining triple fetch) and a slot-finish (the
   completion update duplicated between worker and run). Shrink all
   three functions; preserve the exact field-update ordering (this is
   executor state — ordering IS the behavior).
2. **`load_sos_config`** (`blade/src/sosimg.saw:255`, ~92 lines).
   `doc.section_at(sos)` ×6 and `doc.section_at(chosen)` ×5 exist only
   because `TomlSection` is a NoCopy place. Extract a priorities
   reader and a toolchain-fields reader, each taking `&TomlDoc` + the
   section index and spelling `section_at` once.
3. **builder freshness/stamp dedup** (`blade/src/builder.saw`).
   `build_sos_image` (:300) and `build` (:454) duplicate two blocks
   verbatim: the build-avoidance freshness check and the stamp-write.
   Extract `is_up_to_date(layout: &BuildLayout, hash: &String,
   artifact: String) -> Bool` and `record_build_stamp(layout:
   &BuildLayout, hash: &String)` (exact signatures at the
   implementer's discretion).
4. **CLI flag-scan helper** (`blade/src/cli.saw:59` `parse`, ~99
   lines). Four near-identical `--flag value` scan loops; collapse
   into one small scanner helper.
5. **`String.replace` match helper** (`sawc/std/string.saw:249`,
   ~77 lines). The byte-match loop is written twice (count pass, copy
   pass); extract a private `matches_at(&self, i: Int, old: &String)
   -> Bool` used by both.
6. **cbor `match` rewrite** (`sawc/std/cbor.saw` `transcode` :478,
   `scan` :845). Replace the `if h.major == CborMajor.X` else-if
   chains with exhaustiveness-checked `match` over the raw-backed
   enum. Idiom fix, not extraction; behavior identical.
7. **OPTIONAL — `blade/src/main.saw` `main`** (:150, ~112 lines). Six
   ~90%-identical load-manifest/run-builder/fail blocks. Extract a
   `with_manifest`-style helper taking a closure over `Builder` ONLY
   if it lands as a plain private helper with no new machinery; if it
   wants more design than that, SKIP and say so in the report.

Out of scope (recorded, not owed): the review's nits —
`sosimg.saw::elf_to_sosimg`, `resolver.saw::visit`/`validate`,
`irdet/main.saw::main`, `toml::parse`, `String.to_float`, and all
sos/ candidates.

## Gates

Per unit: full compiler suite (`./.venv/bin/python test_runner.py`).
Final: the tracked battery from the worktree —
`SAW_PYTHON=/Users/swoodtke/Projects/claudes-lang/.venv/bin/python
tools/battery.sh` (full; blade changed, so `bootstrap` and `bench`
checksums are the behavior-preservation oracle; `sos` proves the
untouched kernel still boots).
