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
6. **Nothing depends on recursion depth.** Walks over the program's trees and
   graphs use explicit worklists, and depth limits are language rules with a
   clean diagnostic, never an accident of the implementation's stack (SL-380,
   SL-390).
7. **Every stage has its own test surface** (§5), so a defect is caught in the
   stage that owns it.

## 3. The pipeline

```
source ─► lex ─► parse ─► resolve ─► typecheck ─► lower to MIR ─► borrow check
       ─► drop elaboration ─► monomorphize ─► coroutine lowering ─► emit LLVM IR (text)
       ─► clang/llc + link against the Saw runtime
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
- **Invariants:** nesting beyond 256 is a clean refusal at the opener (one
  depth funnel); flat chains (operators, `else if`) are flat lists (SL-380); no
  recursion on source depth.
- **Existing work:** the M18–M21 prototype parser (arena AST, iterative parsing)
  and U0′'s depth funnel and quote-anchor rules (branch `sl2u0`).

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

### 3.10 Code generation
- **In:** coroutine-lowered MIR. **Out:** textual LLVM IR, compiled and linked
  by clang against the Saw runtime.
- **A mechanical translation** that makes no language decisions.

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

## 6. Open questions

- The MIR's exact shape: SSA or place-based, and how windows appear in it.
- How much of the M18–M21 prototype carries over directly.
- The order of stages built: front to back, or a thin end-to-end slice first so
  the corpus runs early.
- Where the language spec lives, and how its rules are numbered so tests can
  cite them.
