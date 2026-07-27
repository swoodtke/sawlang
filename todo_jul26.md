# Saw Language — Design & Implementation Critique (Jul 26)

A review of the language design and compiler implementation, with prioritized
follow-up work. Findings come from reading the spec/README/TODO plus two
specialist reviews (compiler architecture; typechecker/codegen correctness) and
direct spot-checks of codegen. A third review (test suite) was deferred pending
test-environment reconfiguration.

## Status update (Jul 27, 2026)

Must-fix items 1–6 have landed (briefs in `designs/01`–`05`; every
bug-capture XFAIL test now passes): value-transfer checkpoint, typed AST +
abstract generic checking, canonical mangler, entry-block allocas + O1
pipeline, heap-based interpolation, div-by-zero panics, array const-index
bounds. Item 7's bare-ValueError cleanup and the structural issues (pipeline
unification, merge_into sharing, parser recovery) remain open. Design
decisions: ALL THREE DECIDED AND LANDED — copy semantics (`designs/06`, Copy
trait family, via `designs/09`), `&var` exclusivity (`designs/08`, static
readers-XOR-writer, via `designs/10`), string model (`designs/07`, refcounted
immutable String with atomic retain/release, via `designs/11` — which also
fixed the long-standing `process_simple` stdout-capture bug; the suite has
ZERO xfails as of Jul 27).
Known follow-ups: use-after-move dataflow; deinit/copy conformance-name
mismatch in resources.py (brief 04 report); `--emit-ir` builtins; call-site
`&x` not validated against `&var` param mutability (brief 10 report); field
assignment through a `&var Struct` param fails in codegen (brief 10 report);
immutable `&self` receivers not collected by the exclusivity check
(design-08-vs-brief-10 nuance); `noalias` on `&var` params (brief 10
stretch, deferred); Vector<File>.copy() diagnostic is a Python traceback
(brief 09 report, joins the item-7 cleanup); aggregate/temporary String
leaks — struct fields without declared Deinit, Vector<String> elements,
method-result temporaries used as receivers/args (brief 11 report; bounded,
strictly better than the old leak-everything String); nested no-else `if`
as an if-let branch tail emits an undominated SSA store (brief 11 report,
pre-existing).

## Overall assessment

Genuinely impressive solo language project. Feature surface (generics with
monomorphization, traits with associated types, ADTs with exhaustiveness
checking, a resource-management trait hierarchy, modules, closures, a stdlib
written in Saw, and a package manager written in Saw) is far beyond typical
hobby-language scope. Core engineering decisions are right: structured type
objects instead of strings, a single `Namespace` as the symbol-table source of
truth, rustc-style multi-error diagnostics, dependency-ordered type
registration.

The distinctive design idea worth building around: **references that cannot
escape** (parameters only) let you delete lifetimes from the type system —
close in spirit to Hylo's mutable value semantics.

The core gap: the language's two central promises — memory safety and
deterministic destruction — are **designed but not enforced**. The trait
machinery exists; the checks that would make it sound are missing at most
use-sites. Closing must-fix items 1–3 moves Saw from "impressive demo" to
"credible language."

---

## Language design critique

### Strong ideas (keep)
- No-escape references instead of lifetimes — the key insight of the language.
- `Deinit` / `CustomCopy` / `NoCopy` trait hierarchy with containment rules;
  banning manual `deinit()` calls.
- Distinct `type` aliases with one-way flow (alias → underlying allowed, reverse
  requires construction).
- `for`/`while` as expressions returning `T?` with `break value`.
- Auto-wrapping `Result` returns and the `try`/`try?`/`try!`/`catch` family.

### Design concern 1 — copy-by-default doesn't survive contact with the stdlib
`Vector<T>` and `Map<K,V>` are declared `NoCopy` (`sawc/std/vector.saw:139`,
`sawc/std/map.saw:134`) — necessarily, since bitwise-copying a heap buffer
double-frees. So the most-used types are move-only in practice: users face
Rust-style move discipline without a borrow checker to catch mistakes.
Meanwhile the spec (`LANGUAGE_SPEC.md:437`) says `let list2 = list` does a *deep
copy* for collections — contradicting design principle #4 ("no hidden
allocations"): an innocent `=` becomes O(n) heap work. Three copy semantics
coexist (memcpy / deep-copy / NoCopy-move) and which you get is invisible at the
assignment site.
**Recommendation:** adopt the Hylo/Val position — implicit copy only for cheap
trivially-copyable types, explicit `.copy()` otherwise. Keeps the no-lifetimes
story and lets `Vector` be an ordinary type.

### Design concern 2 — no exclusivity rule for `&var`
Spec never defines aliased mutable references (`swap(&x, &x)`, `&v` + `&var v`).
Without lifetimes you can't check this Rust's way; Swift solved the same problem
with the Law of Exclusivity (static where possible, dynamic otherwise). Saw
needs an explicit answer — "memory safety by default" is a claim about exactly
these cases.

### Design concern 3 — auto-wrap `Result` has an ambiguity hole
`return 42` → `Ok`, `return err` → `Err`, but the dispatch breaks for
`Result<Int, Int>` or any generic `Result<T, E>` instantiated with `T = E`.
Spec must define the tie-break or restrict auto-wrap to unambiguous cases.
The "compiler auto-creates a union type for multiple error types"
(`LANGUAGE_SPEC.md:844`) needs a real spec section: what is the *type* of
`error`? Can it escape the catch block? How does it interact with generics and
the planned `Error` trait?

### Design concern 4 — spec, README, and implementation describe three languages
Concrete drift in load-bearing syntax:
- Match arms: spec uses `pattern => expr` with literal/range/guard patterns;
  impl uses `case Pattern -> expr` and supports none of those patterns.
- Optionals: spec says `some(42)`/`none`; impl uses implicit wrapping + `None`.
- Receivers: spec says `func magnitude(&self)`; README/CLAUDE.md say `(self)`.
- Operator appendix lists `!` as logical NOT; language uses `not` (`!` is
  force-unwrap).
**Recommendation:** per-section status tags (implemented / planned /
aspirational) or split the spec. Currently the spec can't serve as an oracle for
the compiler, which weakens the test suite too.

### Design concern 5 — unspecified core semantics
Must pin down: integer overflow (wrap/trap/UB), division by zero (currently raw
SIGFPE), argument evaluation order, struct equality, and — most importantly —
the **string model**. Strings today are raw NUL-terminated `char*`
(`std/string.saw` casts `String` → `UnsafePointer<Int8>`, calls `strlen`):
O(n) length, no interior NULs, no ownership, unclear UTF-8 story despite the
spec's "UTF-8 string" claim. An owned `{ptr, len, capacity}` string with
`Deinit` should be the first stdlib type designed *after* the copy-semantics
decision, since it stresses every part of the memory model.

---

## Implementation critique

### Done well
- `SawType` is structured, not stringly-typed (`sawc/ast_nodes.py:40`), with
  predicate helpers (`is_result()`, `unwrap_result_ok()`) used almost
  everywhere. This is why the string-matching bugs stand out as exceptions.
- Single `Namespace` consumed by both typechecker and codegen; topologically
  sorted registration (Kahn's algorithm) for modules and mutually-referencing
  structs.
- Monomorphization declares all specialized signatures before generating bodies
  (`codegen/generics.py:405+`).
- Diagnostics: multi-error batching, per-file source tracking, caret rendering
  (`errors.py:86-141`). Real match exhaustiveness checking.
- LIFO scope cleanup across normal exit and early return
  (`codegen/resources.py:185-207`).

### MUST FIX (ranked)

**1. Resource-safety enforced only at some use-sites → double-free reachable via
the stdlib.**
`NoCopy` checked only for identifiers in `let`/`var` and implicit tail returns
(`typechecker/statements.py:405, 526`); function-call args, explicit
`return x`, and struct-field init are never checked. This compiles today:

```saw
func consume(v: Vector<Int>) { }      // scope exit frees v's buffer
func main() {
    var v = Vector<Int>(capacity: 10)
    consume(v)     // should demand `move v` — not enforced
    v.push(42)     // use-after-free
}                  // second free of the same buffer
```

`CustomCopy` has the mirror gap: `copy()` invoked at only 3 of many copy sites
(let, assignment, struct-field init), never for call args, returns, array/tuple
elements, or enum payloads — refcounted types silently get bitwise-copied.
**Fix:** one "value transfer" checkpoint in the typechecker that every
copy/move site funnels through.

**2. Codegen re-implements type inference; its weaker copy causes the leaks.**
Typechecker computes a type for every expression but writes `resolved_type` in
only ~5 places; codegen carries its own ~80-line `_infer_saw_type`
(`codegen/statements.py:139-221`) that returns `None` for match/if/index/
closure/try. That `None` silently disables cleanup registration and copy
insertion — `let x = someMatchExpr()` binding a `Deinit` type just leaks.
**Fix (highest leverage in the repo):** typechecker annotates every expression
node; delete `_infer_saw_type`; codegen becomes a pure consumer. Also unblocks
type-argument inference (`identity(42)` vs `identity<Int>(42)`).

**3. Generic bodies never type-checked, only codegen'd.**
`typechecker/statements.py:196` skips generic function bodies; errors surface
only if/when an instantiation is generated. An unused generic with a type error
compiles clean. **Fix:** a pass that checks each generic body once, abstractly,
against its bounds.

**4. Name mangling exists in three divergent implementations and collides.**
- `codegen/generics.py:125` recurses into type args correctly.
- `codegen/types.py:256-263` ignores them (`identity<Box<Int>>` ≡
  `identity<Box<String>>`).
- `codegen/results.py:484-507` mangles *every tuple* to the literal `"TUPLE"`,
  so `Result<(Int,Int),E>` and `Result<(String,Bool),E>` alias the same LLVM
  struct — silent miscompilation.
- `_wrap_error_in_union` recovers the error type via `mangled.split("_")[-1]`
  (`codegen/results.py:548`) — breaks for multi-segment names.
- Init overloads mangle by *parameter names*, so same names + different types
  collide.
**Fix:** one canonical mangler — length-prefixed, module-qualified,
type-signature-based for overloads. Do this before `-c` separate compilation
makes symbol names a de-facto ABI.

**5. String interpolation is memory-unsafe twice over.**
`codegen/core.py:613-650` allocates a fixed 1024-byte **stack** buffer, fills it
with unbounded `strcpy`/`strcat` (>1KB corrupts the stack), then returns the
`alloca`'d pointer — storing/returning an interpolated string yields a dangling
pointer.

**6. Allocas emitted in loop bodies; zero LLVM optimization passes run.**
No `PassManager`/mem2reg anywhere; IR goes straight to `emit_object`
(`codegen/core.py:814-828`). Loop lowering allocates fresh slots per iteration
(`codegen/loops.py:99-285`). Unoptimized `alloca` in a loop grows the stack
unboundedly — `print("i={i}")` in a hot loop will crash.
**Fix:** emit all allocas in the function entry block; run at least mem2reg.

**7. Assorted safety gaps vs. the "Rust's safety" claim.**
- Fixed-array indexing has no bounds check even for constant indices; the tuple
  path already implements it (`typechecker/expressions.py:852` vs `:865`).
- Integer division by zero SIGFPEs instead of panicking; the `try!` panic
  machinery (`codegen/results.py:77-98`) is a ready-made template.
- 76 bare `raise ValueError` sites in codegen can surface as Python tracebacks —
  `codegen.generate()` is never wrapped, unlike parser calls.

### Structural issues
- **Two divergent compile pipelines** (`compile_saw` vs `compile_with_modules`
  in `sawc.py`) duplicate the back half; a hand-inlined third copy of the
  typechecker registration sequence reaches into private methods
  (`sawc.py:416-436`). Broken result: `--emit-ir` never loads builtins, so it
  fails on any program using `String`/`Vector`/`Result`. Collapse to one
  pipeline (a single file = a module graph of size 1).
- **`merge_into` shares symbol objects by reference and resolves collisions
  first-wins silently** (`namespace.py:722-739`). Codegen-mutable fields
  (`llvm_type`, `specialized_methods`) leak across module namespaces — a
  landmine for incremental/per-module compilation. Cross-module fallback lookup
  scans all modules ignoring visibility, resolving by dict order
  (`typechecker/types.py:74-79`).
- **No parser error recovery**: first syntax error aborts (`parser/core.py:44`)
  though `ErrorReporter` is built for batching. ~40 lines of top-level
  declaration dispatch duplicated between `parse()` and inline-module parsing.
- **Testing is end-to-end only.** 181 integration tests with output/error
  assertions is a solid harness, but no unit tests for lexer/parser/typechecker,
  no differential/fuzz testing, no IR-level assertions. Findings #1–#5 are
  exactly what property tests over copy/move rules would catch.

---

## Priority follow-up (in order)

1. **Fix copy/move enforcement** — single value-transfer checkpoint in the
   typechecker. The language's core promise.
2. **Annotate AST with resolved types; delete codegen's inference.** Highest
   leverage — fixes leak bugs now, unblocks generics inference later.
3. **One canonical mangler + entry-block allocas + default `-O1` pass
   pipeline.** Three contained fixes eliminating whole bug classes.
4. **Decide copy semantics honestly** (deep-copy collections vs. Hylo-style
   explicit copy) and redesign `String` as an owned type. Gates future stdlib
   work.
5. **Reconcile spec ↔ implementation** with per-feature status markers; specify
   `&var` exclusivity, auto-wrap tie-breaks, and the error-union type.

## High-value missing tests (add after test-env reconfiguration)
- `NoCopy` value passed to a function without `move`.
- `CustomCopy` value through call arguments (verify `copy()` invoked).
- Nested-generic instantiations stressing mangling: `Result<(Int,Int),E>` vs
  `Result<(String,Bool),E>`.
- String interpolation >1KB.
- Interpolation result stored/returned past its scope (dangling pointer).
- Million-iteration loop with interpolation (stack growth).
- Fixed-array out-of-bounds constant index.
- Integer division by zero.
