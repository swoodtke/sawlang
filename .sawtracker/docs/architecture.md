# Self-hosted compiler: architecture

The high-level design of the Saw compiler written in Saw. This is a **proposal**
for review: the stages, their contracts, the boundaries between them, and, at a
high level, the mechanism each stage uses. Details are fleshed out when the work
reaches each stage. It follows the Sep 24 2026 freeze of the Python compiler.

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
8. **Every stage's output is plain data.** It can be written out and read back
   (§3.0), so any boundary can become a cache or a package format later
   (§3.12) without changing a stage.

## 3. The pipeline

```
source ─► lex ─► parse ─► resolve ─► typecheck ─► lower to MIR ─► borrow check
       ─► drop elaboration ─► monomorphize ─► coroutine lowering ─► lowered MIR
lowered MIR ─► LLVM IR (text) ─► clang + link against the Saw runtime
            └► VM bytecode ─► interpreter (planned; see §3.10)
```

Everything up to drop elaboration works one module at a time, or one import
cycle at a time where modules import each other (§3.12), and inside that mostly
one function at a time. Monomorphization, coroutine lowering and linking work on
the whole program being built. The driver (§3.12) runs the stages and owns
caching.

### 3.0 What every stage shares

- **Arenas and typed ids.** Every IR is nodes in flat arrays, referenced by
  index. Ids are typed (`ExprId`, `DeclId`, `TypeId`, `LocalId`, `BlockId`) and
  **module-local**: an id is an index within one module's arena, never a value
  from a process-wide counter. This is also the bootstrap subset's requirement
  (§4): arena indices, not references.
- **No stage mutates its input.** A stage produces a new IR, or side tables
  keyed by its input's ids (resolve's name table, typecheck's type table).
  There is nothing to graft onto a node, so the AST-graft class that design 194
  gates in the Python compiler cannot arise.
- **Types are interned by structure.** A type is a `TypeId` into an interner
  keyed by its canonical form: defining module, name, and canonical arguments
  with defaults filled at every depth (SL-382). Two spellings of one type are one
  id. Identity never depends on object identity or on the order in which types
  were first seen.
- **Cross-module references are symbolic.** Inside a module, a reference is an
  index. Across modules it is (module identity, stable declaration path), where
  the path is the qualified name plus, for an overload, its signature. It is
  never an index into another module's arena.
- **Spans are (file, byte range),** and a file is (package, package-relative
  path). No IR contains an absolute path. Paths are rendered only when a
  diagnostic is printed.
- **Diagnostics are records:** a stable ID (SL:testing §5), severity, a primary
  span, labelled secondary spans, notes and fix-its. They are collected per
  checking unit. A unit with errors still produces output, marked poisoned, so
  later stages skip it rather than cascade.
- **Determinism.** Every iteration order is defined, by id or by source order,
  never by hash order or thread timing. Output bytes are a function of the
  inputs alone. Generated symbol names (closures, instantiations, frames) are
  derived from what the code is, such as its enclosing declaration's path and a
  per-declaration ordinal, never from its source line. An edit above a closure
  then leaves its symbol and its cache key unchanged (SL-99). The irdet lane enforces this on the Python compiler. For the new
  one it is also what makes content-addressed caching sound (§3.12).
- **Every boundary has a dump and a verifier.** Each IR has a canonical text
  dump for tests (§5), and a structural verifier that debug builds run at the
  boundary (principle 2).
- **Serializable by construction.** Because every IR is plain data (arenas,
  typed ids, interned keys, symbolic cross-module references, no pointers, no
  closures, no process-global state), any stage's output can be written and read
  back. §3.12 names the boundaries that are.

### 3.1 Lexer
- **In:** bytes. **Out:** a token stream with source positions, and doc-comment
  trivia out of band.
- **Mechanism:**
  - a hand-written scanner over bytes, by longest match. A token is a kind and
    a span. Contextual words (a `default:` label) stay identifiers;
  - literals keep their text. The lexer checks only their form: a numeric
    literal's type and range are fixed by the type it adopts in typecheck, and
    float text converts to a value through the bit-exact routine of design 253;
  - newlines are tokens. Whether one ends a statement depends on brackets, so
    it is the parser's decision (design 129);
  - an interpolated string becomes literal segments plus the token ranges of
    its embedded expressions, which the parser parses;
  - a bad character or an unterminated literal is a diagnostic, and lexing
    continues.
- **Existing work:** `selfhost/lexer` is already the Saw lexer, kept identical
  to the Python lexer by lexdiff.

### 3.2 Parser
- **In:** tokens. **Out:** an arena-indexed AST: nodes in a flat array, children
  by index, every node carrying its span.
- **Mechanism:**
  - recursive descent for declarations, statements and nesting. Binary
    operators and `else if` chains are parsed by loops into flat lists
    (SL-380);
  - postfix chains (calls, members, subscripts, `?.`, `!`, `as` casts) stay
    nested, and each hop charges one level of the 256 depth budget until the
    chain ends (Ruled, SL-380 c2). The 257th hop is refused at that hop. They
    stay nested because they mix node kinds, and real code never chains that
    deep;
  - **the tree records syntax only.** The parser records what was written,
    never what it means. `name(…)` is one `Call` node whatever `name` turns out
    to be, so there is no guess to undo later (§3.3);
  - generic arguments after an identifier use today's bounded speculative
    parse, kept only when `(` or `.` follows;
  - error recovery: on an error, record the diagnostic, skip to the next
    statement or declaration boundary at the same bracket depth, and continue,
    so one run reports every independent error in a file;
  - a `@test(refuses:)` block has only its braces matched in a normal build. In
    a test build its token range is parsed as a unit of its own (SL:testing §5).
- **Invariants:**
  - nesting beyond 256 is a clean refusal at the opener, through one depth
    funnel;
  - flat chains (operators, `else if`) are flat lists, parsed by loops, and
    postfix hops are charged per hop (SL-380);
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
    explicit owner for the source buffer, and a file identity (§3.0).
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
- **In:** the parsed modules being compiled, and the interfaces of the modules
  they import (§3.12). **Out:** a resolution table binding every name
  occurrence to what it denotes, each module's symbol and export tables, and
  the import graph. The AST is not modified.
- **Phase 1, collect.** Every module's top-level declarations go into its
  symbol table before any name inside a signature or body is looked at: types,
  functions (as overload sets), enum cases, traits, statics, extensions and
  conformances. A module's own table never depends on its imports, so collection
  order does not matter and import cycles are harmless. Duplicate declarations
  are refused here.
- **Phase 2, imports.** Each `import` binds names in the importing module, per
  design 150: a qualifier, `.*`, or `.{A, B as C}`. What each module hands on
  to its importers (design 229) is computed by a worklist to a fixpoint, with
  cycle detection (principle 6).
- **Phase 3, signatures and bodies.** With every table complete, each name is
  resolved in its lexical scope, in design 150's order: locals, then module
  declarations, then imported bare names, then qualifiers. Because phase 1
  finished first, a type can mention itself (`struct Node { next: Box<Node>? }`)
  and mutually recursive types and functions resolve in any order.
- **A name resolves to** a local, a declaration, an overload set, an enum case,
  a type parameter, a module or a trait.
- **A call's head is classified here, once.**
  - `Foo(…)` where `Foo` is a type resolves to that type's `init` set;
  - `f(…)` resolves to an overload set;
  - `x(…)` resolves to a local holding a closure value;
  - `T(…)` resolves to a type parameter;
  - `E.Case(…)` resolves to an enum case.

  The Python compiler guesses from one token of lookahead (`name(ident:` is a
  struct init) and then converts in both directions in the typechecker (designs
  66 and 207). Here the question has one owner.
- **What resolve leaves to typecheck** is anything that needs a type. For
  `x.f(…)` on a value, finding `f` needs `x`'s type, and choosing an overload
  needs argument types. Resolve supplies what that lookup needs: each module's
  set of visible extensions, which is its own, its direct imports', and the
  receiver's defining module's (design 142).
- **Rules about names live here:**
  - the visibility of path names (design 80);
  - the shadowing rule: a redefinition is an error unless its initialiser
    mentions the shadowed binding (designs 100 and 107);
  - a test-only name referenced from ordinary code ("`FakeClock` exists only in
    test builds");
  - duplicate and orphan conformances. A conformance lives in its type's or its
    trait's module (design 142).

  Member visibility (fields, methods) needs the receiver's type, so typecheck
  checks it, through the same visibility function.
- **Invariant:** no later stage looks a name up by its spelling.
- **Does not own:** whether a struct has a finite size.
  `struct A { b: B }` with `struct B { a: A }` resolves without trouble. The
  by-value containment cycle is refused by typecheck's layout check.

### 3.4 Type checking
- **In:** the resolved AST. **Out:** typed IR, in which:
  - every expression has a type;
  - every implicit conversion is an explicit node: auto-wrap into Optional or
    Result, literal adoption, `&v` to `&[T]`;
  - every call has its resolved target and instantiation;
  - operators, subscript roles (getitem, setitem, place accessor;
    SL:borrowing §5), `default:` and `for` point at the declarations they call;
  - every expression is marked as a place or a value;
  - every value use carries its transfer kind: a spelled `move`, an implicit
    copy, or the hand-off of an owned temporary (§3.5).
- **Order.** Signatures first, program-wide: struct layouts, function
  signatures, trait requirements and the conformance table. Then each function
  body is its own checking unit, checked against signatures only. No body looks
  inside another, so bodies can be checked in any order, or in parallel.
- **Inference is local and bidirectional.**
  - Signatures are always written. No inference crosses a function boundary.
  - Inside a body, the expected type flows down: a literal adopts it, a
    closure's parameters take it, and a zero-argument construction takes the
    declared slot type (design 207). Argument types flow up.
  - A call site's generic type arguments are solved by local unification over
    its arguments and closure returns, with the later-argument fixpoint and the
    unique-solution rule for overload sets (designs 93 and 105).
- **Generic bodies are type-checked once,** not per instantiation. A body may
  use only what its bounds grant, plus one requirement inferred from the body:
  whether it duplicates a `T` with nothing written at the site. If it does, `T`
  must be Copy-tier, and each call site is checked against the argument it
  passes (design 219). The inferred requirement is part of the function's
  signature summary. So monomorphization cannot produce a *type* error, and a
  generic library is fully type-checked before anyone instantiates it.
  Obligations that depend on a concrete value, such as a `static_assert` over a
  const parameter, are checked per instantiation (§3.8).
- **Overloads.** The candidates are resolve's overload set. Typecheck filters
  them by labels, arity and types. A unique best candidate wins; otherwise the
  call is refused.
- **Traits.**
  - The conformance table maps (type, trait) to its implementation, and default
    bodies fill the gaps.
  - `any Trait` is an existential whose method table is built after
    monomorphization.
  - Test-only conformances sit in a layer that production code never sees
    (SL:testing §4).
- **Copy tier.** One function classifies a type as Copy, ExplicitCopy or NoCopy
  from its members, its declared conformances and the wrappers it passes through
  (design 219). For a generic type, the result is a rule over the type's
  arguments, which monomorphization evaluates.
- **Effects:**
  - `unsafe` is checked per declaration (designs 130 and 136);
  - suspension is inferred, since Saw has no async colouring. A function *may
    suspend* if it contains a park, or statically calls something that may.
    This is a fixpoint over the call graph, computed by a worklist because
    recursion makes cycles;
  - **a generic function's effects are conditions over its type arguments,**
    because the language infers suspension per instantiation: `run<Slow>` may
    suspend while `run<Fast>` does not, and a `sync` caller may call the second
    (spec: suspension, "inference runs per instantiation"). The body is still
    checked once. Its summary records the condition, for example "`run<T>`
    may suspend if `T.step` may", the same way design 219's inferred Copy
    requirement is recorded. Each call site evaluates the condition with its own
    type arguments:
    - where they are concrete, the answer is exact, for the `sync` check and
      for the borrow check alike;
    - where the caller is itself generic, the condition composes into the
      caller's own summary;
    - only *inside* a generic body is a call through a bound (`t.greet()` for
      `T: Greeter`) a conservative "may suspend", unless the requirement is
      declared `sync`;
  - a call through a function value, or a dispatch through `any Trait`, never
    suspends. A closure body cannot suspend, and a dispatch to a suspending
    implementation is refused (spec: suspension);
  - **two effects are tracked, not one.** *May suspend* (above) is about real
    suspension, and it drives the borrow check and framing. *Sync-callable* is
    the conservative guarantee a `sync` body needs. A call is sync-callable if
    its target is known not to suspend, or if its type declares `sync`: a
    `(Int) sync -> Void` function value, or a `sync` trait requirement, even
    through `any Trait` (spec: suspension). A call through a *non-`sync`*
    function value, or to a non-`sync` requirement through `any Trait`, never
    suspends, but it is not sync-callable. The same requirement called through a
    generic bound may suspend (above);
  - sync-callability is carried transitively, through ordinary helper calls and
    in interface summaries, separately from may-suspend. A helper that calls a
    non-`sync` callback is itself not sync-callable, even though it never
    suspends;
  - a `sync` function may call only sync-callable targets;
  - `borrows` and `borrows(sync)` accessor contracts, including the substitution
    rule (SL:borrowing §2.5);
  - `consumes`.
- **Other checks that need only types:**
  - match exhaustiveness;
  - a discarded `Result` (design 151);
  - literal ranges;
  - finite struct size: cycle detection on the by-value containment graph.
- **Does not own:** where moves and drops happen (MIR lowering), or whether a
  borrow conflicts (the borrow check). It records transfers; MIR lowering
  places them.

### 3.5 MIR lowering
- **In:** typed IR, one function at a time. **Out:** MIR.
- **The MIR's shape** (Proposed; §6): place-based and not SSA, like Rust's MIR.
  - A function is a set of locals plus basic blocks.
  - A *place* is a local with a projection path: field, index, deref, enum
    payload.
  - Statements assign an rvalue to a place.
  - Each block ends in one terminator: goto, switch, call, return or
    unreachable.

  LLVM's mem2reg builds SSA later, so the MIR does not need to.
- **Every operand says move or copy.** A value use is `move p`, `copy p` or a
  constant, and one funnel builds every operand from the transfer kind typecheck
  recorded (§3.4). The funnel never invents a move:
  - a spelled `move` moves;
  - an owned temporary (a call's result, a construction) is handed off;
  - a named place of a Copy type copies, running its `copy()` hook if one is
    declared, even at its last use, since skipping the hook would be observable;
  - a named ExplicitCopy or NoCopy place used without `move` is refused, since
    every transfer of one is spelled (spec: the copy tiers);
  - generic forwarding follows its own documented rule (design 219).

  Constructions, arguments, returns, captures and compiler-synthesized calls
  all pass through the funnel, so none can skip the transfer check (SL-340; the
  class of DF-216a).
- **Borrow windows are explicit.**
  - A `borrow` block lowers to `window_open(accessor, args)`, which yields the
    lent reference on a *present* edge, plus an *absent* edge for a conditional
    lend. Then comes the body, and a `window_close` on every edge that leaves
    it.
  - The statement form closes its window as soon as the statement's value is
    copied out (SL:borrowing §2.2).
  - `for` is a window on its head plus a loop calling `next`.
  - A plain `&x` argument is a `ref(shared | exclusive, place)` rvalue.
- **An accessor is lowered as two halves around `lend`** (Proposed). The
  prologue runs at `window_open` and produces the lent reference. The epilogue
  runs at `window_close`. The accessor's locals that live across `lend` form a
  small state record in the caller's frame. That is the shape coroutine lowering
  produces, so accessors reuse its machinery (§3.9).
- **A closure is an aggregate of its captures.** A by-value capture is a move or
  a copy into the closure's record. A reference capture (`[&x]`, `[&var x]`,
  `self`, a reference parameter) is a `ref` whose loan lasts while the closure
  value is live, so the borrow check sees captures as ordinary loans.
- **Evaluation order is fixed here, once:**
  - left to right;
  - a receiver and every key expression evaluated exactly once, into
    temporaries (SL-368);
  - an assignment's right side before its left side's borrow opens;
  - short-circuit operators, `??`, `?.` chains and `try` as explicit branches.
- **`match`** compiles to a decision tree: switches on discriminants, and tests
  on literals, ranges and guards.
- **Scopes end in drops.** Every scope exit gets a `drop(local)` for each owned
  local in scope, in reverse declaration order. It means "drop it if it is
  still initialised", and drop elaboration makes it precise (§3.7). A panic
  aborts (there is no unwinding), so no path needs cleanup edges.
- **Suspension points are marked.** A call to a function that may suspend
  (§3.4) is a *suspension point* in the MIR. §3.9 lowers it, but the borrow
  check sees it first.
- **Op-budget points are placed here too** (design 127). In a function that may
  suspend, every loop backedge gets a budget point:
  - outside any `borrows(sync)` window it is a potential suspension point, which
    the borrow check sees like any other;
  - inside one it only charges the budget, and the yield waits for the next
    budget point after the window closes.

  Coroutine lowering implements these points and never adds a suspension the
  borrow check did not see.
- **The central invariant:** after this stage, nothing about ownership is
  implicit.

### 3.6 Borrow and exclusivity check
- **In:** MIR, one function at a time. **Out:** accepted, or diagnostics.
- **It needs no lifetimes and never looks outside the function,** because a
  reference never escapes one. References are parameters, borrow bindings and
  non-escaping captures. They are never returned or stored in fields (spec, the
  exclusivity section). The only way out of a function is `lend`, whose window
  the *caller* opens and closes. So every loan starts and ends inside the
  function being checked.
- **Two dataflow analyses over the control-flow graph:**
  - **Initialisation.** A forward analysis per place path: definitely
    initialised, maybe initialised, or moved. Using a place that may have been
    moved is a use after move. Moving out of a field is refused, except
    `move self.<field>` inside a `consumes` body, where each field must leave on
    every path or on none (spec: moving a field out). Tracking per place path
    serves that exception and precise diagnostics. It does not authorise other
    partial moves.
  - **Loans.** Every `ref` and every `window_open` creates a loan: shared or
    exclusive, on a place, charging its root as the accessor declares
    (SL:borrowing §3). A `ref` loan lives until its last use. A window's loan
    lives until its `window_close`. Every access, including a move and a drop,
    is checked against the live loans.
- **The conflict rules.** Checking whether two places "overlap" is only the base
  case:
  - **Authorisation.** An access *through* a loan (its binding, its reference,
    or a reborrow of either) is the loan's own use and is allowed. An access to
    the loaned place by any other path conflicts: with any live exclusive loan,
    and, if the access is a write, with any live shared loan.
  - **Tracing.** Derefs and reborrows are traced back to the loan and root they
    came from, so an access through a reference is checked against the right
    root.
  - **Overlap is conservative.**
    - Distinct fields are disjoint, and so are distinct *constant* indices of a
      fixed array.
    - Two dynamic indices (`v[i]`, `v[j]`) are assumed to overlap.
    - A window loan charges its whole root as declared, whatever place was
      lent, so field-disjointness never lets code touch the root under an
      exclusive window.
- **Path-sensitive.** Loans flow along edges, so the absent edge of a
  conditional lend carries no loan (SL:borrowing §2.4).
- **Suspension.** At a suspension point, a live loan from a `borrows(sync)`
  window is refused. Every other loan may span it (SL:borrowing §2.5).
- **Inside an accessor.** Between `lend` and the end of the body, the accessor
  is paused. The lent place must be rooted in `self`, in a parameter, or in a
  window opened in the body (SL:borrowing §2.7). A `borrows(sync)` loan still
  live at `lend` requires the accessor to declare `borrows(sync)` itself.
- **Statics.** A loan rooted in an `unsafe static var` is checked within the
  function only. The rest is the unsafe author's obligation (SL:borrowing §8a).
  The optional `-W` warning is a separate lint over the call graph.
- **Diagnostics name both sides:** the conflicting access, and the loan it
  conflicts with, including where the loan came from (a window, a capture or an
  argument).

### 3.7 Drop elaboration
- **In:** checked MIR. **Out:** MIR where every drop is a concrete operation on
  a concrete path, with drop flags only where control flow requires them.
- **Mechanism.** It reuses the borrow check's initialisation analysis. A
  scope-exit `drop(p)` becomes:
  - a plain drop where `p` is definitely initialised;
  - nothing where it is definitely moved;
  - a drop guarded by a *drop flag* where it is only maybe initialised. Flags
    are boolean locals, set at initialisation and cleared at a move, created
    only for the places that need them.

  After a `consumes` body moves fields out of `self`, the end-of-body release
  drops exactly the fields that stayed. Each field is decided on every path or
  on none, so that needs no flag. Temporaries are dropped at the end of their
  statement, in reverse order of creation.
- **Must-consume types.** Some types forbid an implicit drop: a `Thread` or
  `Task` handle's fate must be written. A value of such a type that reaches an
  implicit drop is refused here, because this is the stage that knows exactly
  where implicit drops happen. Today's runtime drop panic stays as the backstop
  for a handle dropped inside another value's glue.
- **Placement is separate from glue.** This stage decides *where* a drop
  happens. *What* a drop does for a type is that type's glue: its `deinit` body,
  then its fields in reverse declaration order (design 131; spec: the Deinit
  trait), or an enum's payload by discriminant. One place decides a value's lifecycle glue (drop, retain, copy)
  from its type, generated once per concrete type (§3.8). Which glue runs is
  kept separate from whether a value may be copied, the lesson of SL-340.

### 3.8 Monomorphization
- **In:** elaborated MIR, generic. **Out:** concrete MIR per instantiation.
- **Identity:** a type's identity is (defining module, name, canonical
  arguments) with defaults filled at every depth (SL-382).
- **Mechanism: a worklist from the roots.** The roots are `main`, `@export`
  functions, test cases in a test build, the runtime seams, and the methods of
  every `any Trait` table that a concrete type is coerced into.
  - An item is (function, concrete arguments). Substituting into its MIR gives
    concrete MIR, whose calls add new items.
  - Items are deduplicated by identity and processed in a deterministic order.
- **Trait calls become direct calls** to the implementing method. Each
  (concrete type, trait) pair coerced to `any Trait` gets its method table.
- **Glue** (drop, copy, retain) is generated here, once per concrete type, by
  the one glue function (§3.7).
- **A concrete type's copy tier** is evaluated from typecheck's rule (§3.4),
  never re-derived.
- **Const generics** are folded before identity is computed, so `[Int; 2 + 2]`
  and `[Int; 4]` are one type (design 148).
- **Instantiation validation.** No *type* error can occur here, since generic
  bodies were type-checked once (§3.4). But some obligations depend on concrete
  values and are checked here, per instantiation, as ordinary user diagnostics
  with an instantiation trace:
  - a `static_assert` over a const parameter, which the spec provides because
    `where N > 0` is not expressible. The same body must accept `N = 1` and
    report the author's diagnostic for `N = 0`;
  - layout limits of a concrete type.

  An internal error is reserved for a broken compiler invariant, never for an
  invalid concrete argument.
- **Unbounded instantiation** (polymorphic recursion: `f<T>` calling
  `f<Box<T>>`) has no identity cycle to detect. Proposed: refuse it before
  mono, with a check on the generic call graph. A cycle is refused if its
  composed substitution maps a parameter to a type that strictly contains it
  (§6).

### 3.9 Coroutine lowering
- **In:** concrete MIR. **Out:** state-machine MIR: frames, suspension points,
  and the resume function.
- **Which functions become coroutines is decided precisely here.** After mono,
  every *statically dispatched* call, including one through a generic bound, has
  a concrete target. So *definitely suspends* is a fixpoint over those edges: a
  function suspends if it contains a park or statically calls one that
  suspends. Typecheck's conservative "may suspend" (§3.4) served the borrow
  check. A function that turns out not to suspend gets no frame.
- **Calls through a function value or `any Trait` stay unframed.** Mono makes
  type arguments concrete, not the target of a function value. Those calls
  never suspend, since closure bodies cannot and suspending dispatch is refused
  (§3.4). So they embed no frame, and the refusal of a suspending call inside a
  closure body stays as it is (spec: suspension). Framing either one needs a
  driving ABI first, which is the heap-frame design (§6).
- **Frames embed by value.** A suspending function's frame holds:
  - its locals that are live across a suspension point (liveness on the MIR);
  - the state of its open borrow windows;
  - the frames of the suspending callees it drives.

  So a task is one allocation. A cycle in the suspending-call graph has no
  finite frame, so it is refused with the cycle named, as today. A dispatch
  through `any Trait` to a suspending implementation is refused likewise,
  pending heap-allocated frames (spec: suspension).
- **Frame layout is computed here, sized by the high-water mark** (Proposed).
  Frames are laid out callees first, over the suspending call graph, which is
  acyclic. Within a frame, two values may share bytes only when their *storage
  lifetimes* never intersect (codex t16). A storage lifetime runs from
  initialisation through the last thing that needs the bytes: the last use, the
  drop (a deinit may be observable, so last-read liveness is not enough), a
  window's epilogue, and any loan into the value. It covers the code that runs
  between suspension points, the resume and cancel transitions included, not
  only the parked states. A child frame is initialised and polled before its
  first suspension, and its result is moved out before its teardown. Both need
  its storage at moments no parked snapshot shows. That applies to all three
  kinds of content:
  - sequential suspending calls (`a()` then `b()`) overlay their child frames;
  - exclusive branch arms overlay each other;
  - a local or window record live only between two suspension points shares
    with anything live only elsewhere.

  The largest set of values live together is a *lower bound* and the packing's
  goal, not a size formula (codex t17). With fixed offsets over a general
  control-flow graph, the interference need not admit a packing that tight, and
  alignment and padding add to it. The guarantee is the computed layout itself:
  the aligned offsets and total extent that `--emit-frame-layout` reports. For
  sequential child calls, the result is close to the deepest live call chain
  rather than the sum of every call. Parent locals kept across a call, and
  several accessor-window records open at once, still add to it.
  - **One offset for a value's whole life.** A loan may point into a frame
    value across a suspension, and a frame is never relocated (below). So slots
    are assigned by packing values whose live ranges do not intersect, like
    register allocation over states. Nothing is re-laid-out per state.
  - **Teardown is keyed by state, by construction.** The cancel path at each
    state drops exactly the values live in that state, generated from the same
    liveness that assigned the slots. The Python compiler declined this
    overlay (design 163) for lack of state-keyed teardown: its `__release`
    reclaims children through the frame struct's memberwise drop, so sharing
    storage would mean re-keying three teardown sites. That teardown path
    produced silent double frees in designs 124, 131, 134 and 146.
  - **Measured benefit** (design 163, on the Python compiler's corpus, where
    frames are the sum of all children): 13% smaller overall, 36% for the
    frames that can shrink. The sum model grows as branching^depth and the
    overlay as depth: a branching-2 tree saves 45%, 69% and then 82% over
    three levels, and a root with six suspending call sites goes from 6,768 B
    to 928 B. The sawos kernel now runs Saw tasks, and freestanding targets
    are memory-bound (the ESP32-C3 has 400 KiB of SRAM). There, a tight task
    size known at compile time is a real guarantee.
  - The per-frame report (`--emit-frame-layout`, design 163) comes from this
    stage, and design 152's task-frame-size warning can hang off it.
- **Each coroutine becomes** its frame type plus a resume function. The resume
  function switches on the frame's state to the code after each suspension
  point, polls each driven sub-frame, and has a cancel path.
- **Accessors** that keep state across `lend` use the same frame machinery
  (§3.5).
- **The op budget** (design 127) is implemented here, at the budget points MIR
  lowering placed (§3.5). A budget point in a function that turns out not to
  suspend is removed. No new suspension is created here.
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
  - no two values that share frame bytes have intersecting storage lifetimes,
    over parked states and over the resume and cancel transitions alike;
  - only initialised fields are dropped, and the cancel path at each state
    drops exactly that state's live values;
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
  - One LLVM function per concrete MIR function. Each MIR local is an
    `alloca`, which LLVM's mem2reg promotes to registers.
  - Checked arithmetic uses the overflow intrinsics, branching to the runtime's
    panic with `FILE:LINE` (design 122).
  - One target-description module owns layout and each target's C calling
    convention for `extern` calls.
  - The optimisation level passes through the one `speed_level` funnel
    (design 265).
  - Exclusivity facts the borrow check proves can become LLVM `noalias`
    attributes on `&var` parameters (SL-182), added when measurement shows the
    win.
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
    stack overflow is a clean panic. Native targets owe the same: today a
    native overflow is a bare SIGSEGV, and the runtime needs a guard-page
    handler that reports it as a panic (SL-313). The 256 nesting
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

### 3.12 The driver, separate compilation and caching
- **Caching lives in the driver, never in a stage.** Each stage is a pure
  function of its inputs (§3.0), so the driver either runs it or loads its
  output. No stage knows whether its input came from a cache.
- **The front half caches per module, the back half per concrete function:**

  | Artifact | Written after | Contents | Read by |
  |---|---|---|---|
  | Module interface | typecheck (final once its import cycle is solved) | export table, signatures, conformances, copy-tier rules, may-suspend and sync-callable summaries, generic functions' inferred Copy requirements, doc comments | resolve and typecheck of importing modules |
  | Module MIR | drop elaboration | the checked, elaborated MIR of every function, generic ones included | mono, in every program that uses the module |
  | Object code | the backend | concrete functions, per module or per instantiation | the linker |

- **Import cycles are scheduled as one unit** (codex t14). Some of an
  interface's facts come from bodies: may-suspend summaries, and a generic
  function's inferred Copy requirement (§3.4). So modules that import each other
  are processed together, one strongly connected component of the import graph
  at a time, in dependency order:
  1. collect the component's declarations, imports and signatures: a
     *provisional* interface, enough for resolve and for checking bodies;
  2. check every body in the component against those signatures and the
     *final* interfaces of modules outside it;
  3. solve the body-derived facts across the component to a fixpoint;
  4. publish the *final* interfaces, then continue to MIR and the borrow check.

  A module outside any cycle is a component of one. A cached summary of a module
  being rebuilt in the same component is never used as a final fact.
- **Interfaces give early cutoff.** An importer depends on the interfaces of
  what it imports, not on their bodies. Editing a body without changing the
  interface therefore does not re-check the importers. Generic bodies are the
  exception: mono reads their MIR, so changing one re-instantiates it, as in
  Rust and Swift.
- **Keys are content hashes** over:
  - the artifact's inputs: the module's source, and the interfaces it imports;
  - the compiler's own digest;
  - every flag that changes output: target triple and features,
    `--freestanding`, `--runtime-build` and `--runtime-provider`,
    `--no-hidden-alloc`, the test profile, and the optimisation level.

  A wrong key is a silent miscompile, so the key over-approximates
  (design 164, unit 5).
- **Object code is keyed by its actual input** (codex t15): a digest of the
  lowered MIR it is compiled from, plus the compiler and the flags. Lowered MIR
  already contains everything that shapes the code: the imported generic
  bodies it instantiated and the frame layouts of the callees it embeds. So an
  edit to a generic body in module A invalidates module B's object that
  specialized it, even though A's interface and B's source did not change.
  Keying on B's source and imports would miss that. It works the same for a
  package shipped as interface and MIR, with no source.
- **Packages ship interfaces and MIR,** the analogue of a Rust `.rlib` or a
  compiled Swift module, so a dependent never re-parses or re-checks a
  dependency. std is the first such package. The Python compiler's std cache
  (design 168) approximates this with one pickle.
- **The contracts carry what serialization needs from the start** (§3.0):
  - module-local ids;
  - types by canonical key;
  - cross-module references by stable declaration path;
  - spans by package-relative file;
  - diagnostics as part of the output, so a cached module replays its warnings.

  The Python std cache hit three silent failures:
  - a global node-id counter that collided;
  - types shared by object identity across two pickles;
  - absolute paths baked into nodes.

  Each is impossible by construction here.
- **Cache differentials are part of the test surface** (§5). Design 164 made
  them non-negotiable for any cache that ships:
  - **cold versus warm:** the corpus compiled with every cache empty and again
    with every cache warm, every artifact compared byte for byte;
  - **edit, then warm versus clean:** a warm build after an edit compared with a
    clean build of the edited program. The edits include a body-only change, a
    generic-body-only change and a frame-changing change, since identical inputs
    cannot catch a key that misses a dependency.
- **Staging:** the contracts hold from the first stage built. The caches
  themselves come later, driven by measurement. Plain data costs nothing now,
  and retrofitting it is what the Python compiler could not do.

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
  **test sidecar** of the module it tests (`parser.test.saw` beside
  `parser.saw`), which means exactly what an `@test { … }` group in that file
  would, white-box access included. Stage 0's source set excludes
  `*.test.saw`. See SL:testing §4.
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
| Resolution | resolution-table dumps; `@test(refuses:)` for name rules (shadowing, visibility, test-only names); multi-file refusals as corpus files |
| Typecheck | `@test` and `@test(refuses:)` by aspect; typed-IR dumps |
| MIR and its checks | MIR dumps, plus refusal matrices for borrow, move and exclusivity rules |
| Drop elaboration | drop-order and drop-count tests (printing deinits) |
| Monomorphization, coroutines, codegen | runtime `@test` cases; the `examples/` corpus |
| Driver and caching | the cache differentials (§3.12): cold versus warm, and edit-then-warm versus clean, every artifact byte-identical |
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

- **The MIR's exact shape.** §3.5 proposes place-based and not SSA. Still open:
  how an accessor's two halves and their state record appear in it.
- **Generic bodies type-checked once.** §3.4 depends on it. A sweep is owed for
  any language feature that today relies on checking per instantiation, beyond
  the two named: design 219's inferred Copy requirement, and value obligations
  like `static_assert` (§3.8).
- **Suspension through a generic bound, inside a generic body.** Call sites with
  concrete type arguments are exact (§3.4). Inside a generic body, `t.greet()`
  for `T: Greeter` is a possible suspension unless the requirement is `sync`.
  So a `borrows(sync)` window held across such a call *in a generic body* is
  refused, even if every instantiation is sync. Is that acceptable, or should
  such a requirement be declared `sync`? Calls through a function value or
  `any Trait` are not affected, since they never suspend.
- **Polymorphic recursion** (§3.8): the proposed static refusal on the generic
  call graph.
- **Heap-allocated frames,** which the spec leaves pending for suspending
  recursion and for suspending dispatch through `any Trait`. The frame design
  must leave room for them.
- **The serialization format** for §3.12's artifacts: its binary encoding, its
  versioning, and whether it shares a schema with the text dumps.
- **What `#file` renders** once no IR holds an absolute path: a
  package-relative path, or something else.
- How much of the M18–M21 prototype carries over directly.
- The order of stages built: front to back, or a thin end-to-end slice first so
  the corpus runs early.
- Where the language spec lives. (Its rules get stable names, not numbers,
  which tests cite: SL:testing §6.)
