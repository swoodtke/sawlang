# Saw Language Project — Development Guide

Saw: a systems language (Rust safety + Swift ergonomics, no lifetimes,
deterministic destruction). This file covers HOW TO DEVELOP the
compiler/tooling. For HOW TO WRITE Saw code, load the **saw-lang
skill** (`.claude/skills/saw-lang/`); the authoritative language
reference is **LANGUAGE_SPEC.md**. Open work: **designs/todo.md**
(tracker); decided designs: `designs/NN-*.md`.

## Repo map
```
sawc/              # Compiler: Python + llvmlite
  sawc.py          # CLI; lexer.py; parser/; ast_nodes.py
  typechecker/     # Type checking passes (mixin classes)
  codegen/         # LLVM IR generation (mixin classes)
  coro_transform.py# Source-level coroutine transform
  builtin.saw      # Built-in traits; std/ = stdlib (.saw)
examples/          # Compiler test suite programs (test_runner.py)
blade/             # Blade package manager (written in Saw)
libs/              # Real Saw library packages (semver, toml)
tools/blade_bootstrap.py  # Self-hosting bootstrap loop
designs/           # Design briefs + todo.md tracker
sos/               # SOS kernel design notes (App-2)
```

## Python environment
Dependencies live in `.venv/` (Python 3.14, llvmlite). ALWAYS use it:
```bash
./.venv/bin/python test_runner.py
./.venv/bin/python sawc/sawc.py examples/hello.saw -o hello
```
The Makefile calls bare `python3`, so `make test` needs the venv
activated first.

## Compiler usage (dev)
```bash
./.venv/bin/python sawc/sawc.py <src.saw> [-o out] [-v] [-c]
    [--emit-ir] [--emit-ast] [-O0] [--module-path NAME=DIR]
```
Default pipeline is O1-style. `--module-path` maps a package name to a
module dir (Blade uses this per dependency).

## Testing
- `make test` (venv active) or `./.venv/bin/python test_runner.py` —
  full compiler suite, ~1 min uncontended. Multi-pattern filter:
  `./.venv/bin/python test_runner.py -f test_a,test_b`. Zero xfails is
  the bar; run the FULL suite before every commit.
- Never run two suite invocations at once.
- Tests support a `// COMPILE-FLAGS:` directive (`{TESTDIR}`
  placeholder).
- App-level: `blade test` (tests/*.saw exit 0 = pass; see TESTING.md);
  `./.venv/bin/python tools/blade_bootstrap.py` or
  `make blade-bootstrap` runs the self-hosting loop (stage0→stage2).
- Pyright diagnostics on sawc/ are NOISE (mixin `self.X` false
  positives) — ignore unless a real behavior test fails.

## Scratch compilations
For throwaway experiments do NOT write .saw files to /tmp or via
heredocs/echo (not auto-approved). Instead:
1. Write the file (Write tool) under `.build/scratch/` (gitignored)
2. `./.venv/bin/python sawc/sawc.py .build/scratch/foo.saw -o .build/scratch/foo`
3. `./.build/scratch/foo`

## Command hygiene (avoids permission prompts)
- Read files with the Read tool (batch multiple Reads); never `cat`
  via Bash loops.
- Navigate sawc/ Python with the LSP tool (workspaceSymbol,
  goToDefinition, findReferences); Grep/Glob for text search. Plain
  read-only `grep`/`ls` are allowlisted fallbacks; `find`/pipelines
  are not.
- NEVER prefix commands with `cd <path>;` — the working directory is
  already the repo root, and compound wrappers break allowlisting.
- NEVER run inline Python (`python -c`, `python - <<EOF`). Write
  probes to `.build/scratch/probe_*.py` and run with
  `./.venv/bin/python .build/scratch/probe_foo.py`.
- No shell heredocs; no `sed`/`awk` edits (use Edit).
- Commit messages containing backticks: write to a file, use
  `git commit -F <file>`. Never pipe via stdin/heredoc.
- `git add` explicit paths only — never `-A`/`.`.

## Design-brief workflow
Design decisions are made WITH the user, recorded as `designs/NN-*.md`
briefs, implemented by dispatched agents (one at a time on `main`;
concurrent only in isolated worktrees, cherry-picked back — linear
history, no merge commits). Each brief lands in small per-unit commits,
full suite green each. Docs convention: spec + saw-lang skill get
feature updates (NOT this file). Standing policy: fix user-facing bugs
on discovery unless genuinely ambiguous (then tracker + flag). Record
language pain hit while writing Saw as DF-findings in the tracker.

## Language state (orientation digest — details in spec/skill)
Landed through design 67 (Jul 30): full trait system (default bodies,
`any Trait` existentials, Equatable/Comparable/Hashable/Printable/
Error), overloading + labeled arguments (lenient model), generics with
default type params, Copy trait family + move checkpoint + Law of
Exclusivity, Result/Optional with auto-wrap + erased
`Result<T, Box<any Error>>`, patterns (literals/ranges/guards/tuple
destructuring) + named tuples, collection literals (Map/Set/Vector),
colorless concurrency (coroutine transform + TaskGroup + channels),
allocator type params + Box/slab + statics/Atomic + UnsafeMemory +
`@export`/`@section` (freestanding-ready), platform-width Int,
bounds/overflow/shift checks always on. Member visibility (design 80):
struct fields + extension methods are private-by-default outside the
defining module (std under the gate too). Blade (package manager in Saw)
is self-hosting. License: Apache-2.0 WITH LLVM-exception.
