# Self-hosted compiler: architecture

The high-level design of the Saw compiler written in Saw. This is a **proposal**
for review: the stages, their contracts, and the boundaries between them. Each
section will be fleshed out when the work reaches it. It follows the Sep 24 2026
freeze of the Python compiler.

## 1. Why a new architecture

Almost every soundness bug found in the Python compiler during September has the
same shape: **one rule, enforced separately at several sites, with one site
missing.** Examples:

- intercepted constructions that skipped the value-transfer check (SL-340);
- implicit closure captures that skipped exclusivity (SL-345);
- drop code with no path for layout-transparent wrappers (SL-340);
- a hand-maintained save/restore list (SL-356);
- a depth bound meant for alias cycles that counted every level of nesting
  (SL-390).

Sweeps kept finding siblings, because the Python compiler has no layer where
ownership is explicit. Moves, copies, drops and borrows are decided partly as
typechecker annotations, partly again in codegen, and the coroutine transform
rewrites source that is then typechecked a second time.

The fix is structural: **each fact is decided exactly once, in one stage, and
every later stage consumes it rather than re-deriving it.** Rewriting the
compiler in Saw is the occasion. The architecture is the point.

## 2. Principles

1. **Each fact has one owner.** Name binding belongs to resolution. Types belong
   to the typechecker. Where values move, copy, drop and borrow belongs to MIR
   lowering and the checks that run on the MIR. Later stages read these facts
   and never recompute them.
2. **Stages have contracts.** Each stage states its input, its output and the
   invariants its output guarantees. A later stage may assume those invariants,
   and a debug build checks them at the boundary.
3. **No reaching back.** No stage consults an earlier stage's internal data
   structures. It gets what it needs from its input.
4. **Rules that apply "at every position" are funnels.** One function, with its
   entry points named, never a copy of the rule at each site.
5. **Diagnostics are values.** Errors are collected per checking unit, never
   thrown in a way that aborts compilation. This is what lets `@test(refuses:)`
   blocks be checked on their own.
6. **No accidental stack exhaustion on valid input.**
   - Depth limits are language rules with a clean diagnostic, never an accident
     of the implementation's stack (SL-380, SL-390).
   - Flat constructs (operator chains, `else if` chains, statement lists) are
     flat in the tree and handled by loops.
   - **In syntax parsing,** recursion is allowed only where every recursive
     cycle crosses the depth funnel, so it is bounded by the 256 nesting rule.
   - **Semantic dependency graphs are not bounded by source nesting.** A long
     chain of shallow type aliases or generic dependencies has no deeply nested
     source, and a call graph can be arbitrarily deep. So these graphs are
     walked with worklists and identity-based cycle detection, never with a
     depth budget. Imposing the parser's budget on them would recreate SL-390.
   - A syntax level is not one call frame, so the worst mixed-depth call chain
     is measured on every supported native and VM stack before 256 is claimed
     as supported.
7. **Every stage has its own test surface** (§5), so a defect is caught in the
   stage that owns it.

## 3. The pipeline

```
source ─► lex ─► parse ─► resolve ─► typecheck ─► lower to MIR ─► borrow check
       ─► drop elaboration ─► monomorphize ─► coroutine lowering ─► lowered MIR
lowered MIR ─► LLVM IR (text) ─► clang + link against the Saw runtime
            └► VM bytecode ─► interpreter (planned; see §3.10)
```

Each stage is outlined here and fleshed out later.

### 3.1 Lexer
- **In:** bytes. **Out:** a token stream with source positions, and doc-comment
  trivia out of band.
- **Existing work:** `selfhost/lexer` is already the Saw lexer, kept identical
  to the Python lexer by lexdiff.

### 3.2 Parser
- **In:** tokens. **Out:** an arena-indexed AST: nodes in a flat array, children
  by index, every node carrying its span.
- **Invariants:**
  - nesting beyond 256 is a clean refusal at the opener, through one depth
    funnel;
  - flat chains (operators, `else if`) are flat lists, parsed by loops (SL-380);
  - recursion only through the funnel, as principle 6 describes, with every
    recursive call cycle proved to cross it.
- **Starting point** (Ruled; codex concurs, architecture t8). Carry over from the
  M18–M21 prototype (`prototypes/parser/`), as contracts and infrastructure:
  - **arena invariants:** backward edges, contiguous ordered child ranges,
    unique child ownership and reachability, and span checks;
  - **independently authored fixtures:** precedence, delimiters, statement
    versus tail, newline lookahead, and syntax-only acceptance;
  - **the harness:** lossless framed dumps, exact cross-engine comparisons,
    deterministic batching, and failure artifacts. M21's renderer profiling and
    batching work stand on their own, independent of its parser control stack;
  - from U0′ (branch `sl2u0`): the complete depth funnel, the lane proving every
    recursive path is charged, and the quote-anchor rule.
- **Carried over, but not as-is:**
  - M21 stores `else if` as nested If/Block/FinalExpression wrappers and charges
    each active `else if` against the depth budget. The new contract makes
    `else if` a flat list, so those arena and depth expectations change
    explicitly, even where the source grammar is unchanged;
  - the canonical dump schema and the engine adapters migrate on purpose. Byte
    parity is not kept blanket;
  - prototype spans are token-index ranges and the tree keeps neither source
    nor tokens. Replacing per-node text with spans into the source needs an
    explicit owner for the source buffer, and a file identity.
- **Not taken:** the fully iterative continuation-stack parsing. It exists
  because the prototype runs inside the mini-VM, whose call stack is small, and
  it costs several work kinds and frames per construct (`if`/`else` alone took
  about 660 lines). The new parser is **bounded recursive descent**: recursion
  is capped at 256 by the language's depth rule, and flat chains are loops. The
  VM backend's stack is sized for that bound (§3.10).
- **Also rework:**
  - first-error-only failure becomes per-unit diagnostics (principle 5);
  - the global scans when closing blocks and collecting arguments;
  - the append-only frame snapshots;
  - per-node text copies, which become spans into the source.
- **The oracle changes.** Parity with the Python parser holds only for
  constructs whose grammar did not change. The spec's numbered rules are the
  authority for `borrow`, `@test`, subscripts and slices.

### 3.3 Name resolution
- **In:** the AST. **Out:** every name bound to a declaration id; imports,
  visibility (design 80) and module identity resolved.
- **Invariants:** no later stage looks a name up by its spelling.

### 3.4 Type checking
- **In:** the resolved AST. **Out:** typed IR, with every expression's type and
  every call's resolved target and instantiation.
- **Owns:** inference, trait resolution, overloads, copy-tier classification,
  and effects (`sync`, `unsafe`, `borrows`, `consumes`).
- **Does not own:** where moves and drops happen. It records transfers; MIR
  lowering places them.

### 3.5 MIR lowering
- **In:** typed IR. **Out:** MIR, a control-flow graph of basic blocks over
  *places*, with every ownership operation explicit: `move`, `copy`, `drop`,
  `borrow(shared|exclusive)`, `lend`/window open, and window close.
- **Owns:** evaluation order, temporaries and their lifetimes, and the lowering
  of `borrow`, `for`, `match`, `try` and closures.
- **The central invariant:** after this stage, nothing about ownership is
  implicit.

### 3.6 Borrow and exclusivity check
- **In:** MIR. **Out:** accepted, or diagnostics.
- **One pass** checks the law of exclusivity, use-after-move, and the root
  charges of borrow windows (declared modes, see the borrowing doc). It is
  path-sensitive: an absent conditional lend holds no borrow.

### 3.7 Drop elaboration
- **In:** checked MIR. **Out:** MIR where every drop is a concrete operation on
  a concrete path, with drop flags only where control flow requires them.
- **One place** decides a value's lifecycle glue (drop, retain, copy) from its
  type. Which glue runs is kept separate from whether a value may be copied, the
  lesson of SL-340.

### 3.8 Monomorphization
- **In:** elaborated MIR, generic. **Out:** concrete MIR per instantiation.
- **Identity:** a type's identity is (defining module, name, canonical
  arguments) with defaults filled at every depth (SL-382).

### 3.9 Coroutine lowering
- **In:** concrete MIR. **Out:** state-machine MIR: frames, suspension points,
  and the resume function.
- **Operates on MIR,** not source, so it never re-typechecks generated code.
  Borrows across suspensions are windows in the frame.
- **Suspension is visible to the borrow check.** Effects are known after type
  checking, so suspension points already appear in the MIR the borrow check
  sees, and coroutine lowering introduces no new ownership operations. SL-385,
  SL-386, SL-315 and SL-256 were all a borrow or capture crossing a suspension
  in a transform that rewrote source.
- **The executor protocol is MIR primitives, correct by construction.** One
  `park(root_token, fd, dir)` op, whose single lowering records the park word
  and then arms readiness, and one propagation op, whose single lowering merges
  a child's wake reason. There is nothing to verify by pattern-matching emitted
  code. SL-353's lost wake came from arming before recording, and SL-355's
  after-the-fact verifier had holes in three successive review rounds.
- **Ownership preservation is verified, not re-decided.** The borrow check runs
  before this stage, so it cannot see the new resume, cancel and drop paths
  that lowering creates. A MIR verifier after lowering checks that:
  - a frame is never relocated while a live loan points into it;
  - only initialised fields are dropped;
  - cancellation closes active borrow windows and runs their epilogues in
    reverse order, exactly once.
  This checks that lowering preserved the earlier ownership decisions. It is
  not a second implementation of borrow policy.

### 3.10 Backends
- **The backend boundary is lowered MIR:** after monomorphization and coroutine
  lowering, everything is concrete and every ownership operation is explicit.
  Every backend consumes exactly this and nothing earlier.
- **LLVM backend (the primary one):** textual LLVM IR, compiled and linked by
  clang against the Saw runtime.
- **VM backend (planned, and the design must keep it possible):** MIR to VM
  bytecode, run by an interpreter. Requirements this places on the earlier
  stages:
  - the MIR stays target-independent: no LLVM types leak into it, and layout
    comes from one target-description module that every backend queries;
  - coroutines are already state machines in the MIR, so the VM needs no native
    coroutine support;
  - runtime seams (`__saw_rt_*`) reach a VM through a host-call table, and
    extern calls through an FFI bridge;
  - the VM has an explicit frame stack with defined exhaustion behaviour: a
    stack overflow is a clean panic, as on native targets. The 256 nesting
    limit bounds source syntax, not runtime call depth, since a shallow function
    can recurse as deeply as its input drives it. So the limit cannot size the
    VM stack for general programs. It only sizes the parser's own recursion,
    which is a capacity estimate for running the compiler itself inside the VM.
- **A MIR interpreter also serves compile-time evaluation.** `const func` (if
  adopted) can run on the same interpreter, as Rust's const evaluation runs on
  MIR, so a VM backend and compile-time evaluation share one engine.
- **Every backend is a mechanical translation** that makes no language
  decisions. MIR invariants enforce that:
  - **operator semantics are resolved once.** `x op= y` lowers to the same typed
    binary op as `x op y`, plus a store, with signedness and checked/wrapping
    behaviour carried on the op, never re-derived at emission (SL-370: compound
    `/=` picked `sdiv` independently of `/`'s `udiv`);
  - **receivers are places.** Every call's receiver is an explicit MIR place or
    value, so no backend chooses "load, then spill" (SL-368: an Atomic store
    through `p[i]` hit a copy);
  - **no per-function mutable state in a backend** beyond its builder (SL-356:
    a hand-maintained save/restore list missed a member).

### 3.11 Runtime
- The existing Saw-authored runtime (`sawc/rt/`) behind the frozen ABI
  (`rt/ABI.md`), shared with the Python compiler. Lock re-entry panics under the
  new contract (see the borrowing doc).

## 4. Bootstrap

1. **Stage 0:** the frozen Python compiler compiles the Saw compiler.
2. **Stage 1:** the result compiles the Saw compiler again.
3. **Stage 2:** that result compiles it a third time, and stages 1 and 2 must
   produce identical output.

The Saw compiler's own source is written in a **conservative subset** that the
frozen compiler builds correctly: arena indices rather than references in data
structures, no closures with captures, no coroutines, shallow types. It avoids
every shape in the hazards ledger.

**What source Stage 0 builds** (Ruled Sep 24; codex's question in t6). The frozen
compiler cannot parse the new forms (`borrow`, `@test`) and must not be
unfrozen to learn them. So:
- The compiler's own source is written in the **intersection** of the two
  languages: code that is valid in both and means the same in both. Examples:
  a plain `v[i]` copy read, arena indices, explicit methods rather than inline
  place writes, and no `borrow` or `@test`.
- The compiler's **own tests** live in separate files that only Stage 1 onward
  compiles, so the first test-first build has no dependency cycle. Each is a
  **test sidecar** of the module it tests: it is part of that module in test
  builds, so its tests keep white-box access, and it is never in Stage 0's
  source set. See SL:testing §4.
- The subset checker (below) enforces the intersection over the compiler
  source, so Stage 0 always sees code it builds correctly.
- The alternative, a bootstrap projection tool that strips `@test` blocks and
  rewrites new spellings, adds a tool and a second meaning for the same source.
  It is not proposed.

**The subset is enforced mechanically, not by convention.** "Avoid every shape"
as a convention is the same one-rule-many-sites discipline §1 diagnoses. A small
checker, a battery lane over the compiler's own source, refuses the ledger's
shapes. Examples: a closure argument to `with_ref`/`with_var_ref`/`each` that
names the borrowed root (SL-345), an Atomic or cell method called directly on
`p[i]` (SL-368), any coroutine, any closure capture. Each ledger entry says
whether the checker covers it.

## 5. Testing, per stage

| Stage | Test surface |
|---|---|
| Lexer | token dumps; lexdiff against the frozen lexer |
| Parser | canonical AST dumps (the M21 format); `@test(refuses:)` does not apply to parse errors, which stay as corpus files |
| Resolution / typecheck | `@test` and `@test(refuses:)` by aspect; type dumps |
| MIR and its checks | MIR dumps, plus refusal matrices for borrow, move and exclusivity rules |
| Drop elaboration | drop-order and drop-count tests (printing deinits) |
| Monomorphization, coroutines, codegen | runtime `@test` cases; the `examples/` corpus |
| Whole compiler | the `examples/` corpus (~2,700 programs), differential against the frozen compiler; the bootstrap fixpoint |
| Backends | the same cases run on every backend (LLVM, and the VM when it exists), compared with each other, as the prototype's multi-engine harness already does |
| Freestanding (downstream) | the sawos gate: 382 QEMU cases across three profiles, about 25 minutes on the tracker server, pinned by sha. It covers what `examples/` mostly does not: freestanding riscv32 (`+m,+a,+c`) and aarch64 at `-Oz`, `--runtime-provider` seam checking, `--no-hidden-alloc`, `@export`/`@section`/`@align`, `unsafe static var` as the main state, Saw tasks inside the kernel (`tests/taskdump.saw`), and Blade-built packages in boot images. Each case checks its own console transcript (tools/sos_runner.py), so it is NOT differential, and a failure there is adjudicated by the case's assertion. Its flag list doubles as sawos's migration checklist: sawos stays on the frozen compiler until the new one accepts those flags |

**Two kinds of expected mismatch, annotated separately.** When the new compiler
disagrees with the frozen one, the difference is either the frozen compiler
being known wrong (`oracle known wrong: SL-nnn`), or the language having
changed on purpose (`language changed: <spec rule>`). Examples of the second:
`Map.[]` no longer returns an optional, and the inline place spellings are
retired. Any other mismatch is presumed to be a new-compiler bug until shown
otherwise.

**The frozen compiler is an oracle with known wrong answers.** Everything parked
under the freeze stays wrong in it: SL-368 (an Atomic through `p[i]` acts on a
copy), SL-345 (the capture use-after-free compiles), SL-387 (nested captures lose
writes), SL-353 (a lost wake), and any hazard not yet found. A mismatch is
adjudicated against the EXPECT directives and the spec, never assumed to be the
new compiler's bug. The hazards ledger doubles as the list of places the oracle
is known to be wrong, and a per-case "oracle known wrong: SL-nnn" annotation
keeps that auditable.

## 6. Open questions

- The MIR's exact shape: SSA or place-based, and how windows appear in it.
- How much of the M18–M21 prototype carries over directly.
- The order of stages built: front to back, or a thin end-to-end slice first so
  the corpus runs early.
- Where the language spec lives, and how its rules are numbered so tests can
  cite them.
