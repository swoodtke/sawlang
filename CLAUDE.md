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
  rt/              # Runtime ABI (design 113/113b, v2 by 117): rt/ABI.md freezes
                   # the __saw_rt_* seam contract; the seam bodies are AUTHORED
                   # IN SAW here — common/ (os_ops.saw = status-carrying tcp/fs/
                   # env ops) + host_macos/ + host_linux/ (reactor.saw kqueue/
                   # epoll, net_os.saw errno->SysError) (.saw, --runtime-build)
                   # + shim.c (3 FFI-blocked bodies: write/panic, thread_spawn+
                   # offload thunk, set_nonblocking). Built + cached under
                   # .build/rt/, auto-linked for hosted builds. Design 117: the
                   # reactor is now Saw too (instance-based); the compiler only
                   # synthesizes the process-global __saw_reactor getter.
examples/          # Compiler test suite programs (test_runner.py)
blade/             # Blade package manager (written in Saw)
libs/              # Real Saw library packages (semver, toml)
tools/blade_bootstrap.py  # Self-hosting bootstrap loop
designs/           # Design briefs + todo.md tracker
sos/               # SOS kernel: spec.md notes + kernel/ (M0 riscv32 QEMU
                   #   target: boot.S/virt.ld/rt.c + main.saw) + tests/.
                   #   `make sos-test` (tools/sos_runner.py) boots it under QEMU
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
    [--emit-ir] [--emit-ast] [--emit-docs] [--emit-docs-all] [-O0]
    [--target TRIPLE] [--module-path NAME=DIR]
    [--freestanding] [--runtime-build]
```
That is the complete flag set (`sawc.py:1125-1156`); `-o` defaults to
`.build/<source>`.
Default pipeline is O1-style. `--module-path` maps a package name to a
module dir (Blade uses this per dependency). `--runtime-build` (design
113b) compiles a Saw runtime that `@export`s the frozen `__saw_rt_*` ABI
(sync-only, object output) — used to build `sawc/rt/`; the hosted runtime
objects are built + cached under `.build/rt/` and auto-linked (delete
`.build/rt/` to force a rebuild; `-v` lists the linked objects).

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
full suite green each. Docs convention (design 125): LANGUAGE_SPEC.md
(authoritative), the saw-lang skill, AND README.md get feature updates
— NOT this file, whose digest below is only an orientation summary.
README carries the user-facing subset: anything a reader would pick Saw
for, plus the CLI / stdlib surfaces it already lists. User-facing prose
follows the saw-docs skill. Standing policy: fix user-facing bugs
on discovery unless genuinely ambiguous (then tracker + flag). Record
language pain hit while writing Saw as DF-findings in the tracker.

## Language state (orientation digest — details in spec/skill)
Landed through design 121 (Aug 4): full trait system (default bodies,
`any Trait` existentials, Equatable/Comparable/Hashable/Printable/
Error), overloading + labeled arguments (lenient model), generics with
default type params + default VALUES that drive inference (108) +
type-argument INFERENCE at call sites — args, closure returns,
overload sets (unique solver wins, ties error), later-arg fixpoint,
labeled mapping (93, 105) — with bounds checked for EVERY type arg
incl. primitives (109), Copy trait family + move checkpoint + Law of
Exclusivity, Result/Optional with auto-wrap + erased
`Result<T, Box<any Error>>`, full Swift-style optional chaining (111:
`a?.b?.c()` arbitrary length incl. call heads + method hops, one short-circuit
skips the rest of the postfix chain incl. args, flattening never `U??`, final
field must be copyable; chained assignment `x?.y = v` writes the payload in place,
types `Void?`, consumed via the `_`-blessed `if let`/`guard let`; a suspending
hop and a suspending chain both work since 120),
patterns (literals/ranges/guards/tuple
destructuring) + named tuples, collection literals (Map/Set/Vector),
platform-width Int, bounds/overflow/shift checks always on,
`#file`/`#line`/`#function` definition-site literals (98), shadowing
= error unless derived from the shadowed binding — incl. same-scope
redefinition and for-loop vars via the mentions-rule (100, 107).
Colorless concurrency: coroutine transform + one ambient cooperative
scheduler (89-b/c: live accept-loop servers work; op-budget fairness
backstop) + TaskGroup (MT via `threads: N`, Send-checked) + channels +
precise reactor wakeup (91) + cancel wakes even an io-parked task
(102) + `extern blocking` calls RUN via thread offload (103);
suspending calls embed at any nesting depth / control-flow position
or error cleanly — never silently block (96, 101, 104) — and, since 120,
in any EXPRESSION position too (chains, args, receivers, operands,
literals, interpolation, return, `try!`, `?.` hops, value if/match,
`??`/`&&`/`||` RHS) via an ANF hoist in coro_transform that preserves
evaluation order and short-circuits; references
span suspends (88) and forward onward as re-borrows (106) + whole-referent
replacement `x = v` / `self = v` through `&var` (110: uniform with closures,
erased `&var any Trait` excluded, Box payload-swap works); std.net
owning TcpListener/TcpStream (failable ops return Result, EOF distinct
from error — 84-92). Freestanding toolkit: allocator type params +
Box/slab + statics/Atomic + UnsafeMemory + `@export`/`@section`.
Member visibility (design 80): struct fields + extension methods are
private-by-default outside the defining module (std under the gate
too — design 82 makes each std FILE its own module). Prelude
discipline (design 82): only a curated core is auto-visible
(primitives, Vector/Map/Set, Optional/Result/Box/Arc/Allocator, the
trait vocabulary, the builtins + concurrency primitives,
StringBuilder); File/Data/Channel/Mutex/net/IoError/Utf8Error/process/
env/time — and `yield_now` (std.task, design 114; the cooperative-yield
wrapper over the now stdlib-internal intrinsic) — need
`import std.<module>` — so a user type named `IoError`/`File` no longer
collides. Unsafe surface (design 81):
unsafety is type-carried, plus an `unsafe` expression marker required
wherever a raw pointer flows invisibly — a deref/index/write, pointer
arithmetic, or binding a pointer produced by a call — in a function whose
signature carries no `Unsafe*` type (a pointer-naming cast, a
pointer param/return/field, or a `self`-method of a pointer-field struct is
already the marked domain); `Vector.with_ref`/`with_var_ref` (scoped,
invalidation-proof element borrow) replaced `ref_at`. Doc comments (121):
`///` (following decl) + `//!` (module) lexed as trivia in BOTH lexers
(lexdiff parity, `--docs` dump), parser-attached with unattached-doc
errors, `--emit-docs` JSON of the typechecked surface (design-80 gate on
members); std.task + std.time docstringed; the saw-docs skill is the
style guide for all user-facing doc text. Blade (package manager
in Saw) is self-hosting. License: Apache-2.0 WITH LLVM-exception.
