# Compiler pre-port architecture review — what to restructure in Python NOW

**Date:** 2026-08-04 · **Main:** f764b75 · **Scope:** `sawc/` (44,612 LOC Python)
**Question asked:** not "is this good code" but **"what, changed in Python today,
makes the eventual Saw port mechanically simpler?"** Everything below is
justified by port mechanics. Aesthetic findings were dropped.

Reference points: the lexer pilot (`selfhost/lexer`, design 116) is the only
completed port — 1,802 LOC of Saw against 808 LOC of Python, validated by a
**differential dump harness** (`make lexdiff`, zero mismatches over the whole
`.saw` corpus). That harness shape is the template every later stage should
reuse, and it is the main constraint on port ORDER.

---

## 0. Method

Static analysis over all 45 `sawc/*.py` files (probes under
`.build/scratch/probe_crev_*.py`), plus targeted reading of the pipeline driver,
the three composed classes, and the coroutine transform. No repo file outside
this report was modified; no suite was run.

---

## 1. The shape today

### Per-stage size (port cost proxy)

| Stage | LOC | Composed from |
|---|---:|---|
| `lexer.py` | 808 | one class, 17 methods — **ported** |
| `parser/` | 3,929 | `Parser` + 4 mixins |
| `ast_nodes.py` | 1,517 | 95 classes / 93 dataclasses — 80 AST nodes (44 `Expression`, 21 `ASTNode`, 9 `Statement`, 6 `Pattern`), 2 enums, **13 with no base at all** incl. `SawType`, `Argument`, `Parameter` and four top-level decl types |
| `namespace.py` | 1,553 | `Namespace` (70 methods) + 9 symbol dataclasses |
| `typechecker/` | 15,174 | `TypeChecker` + 5 mixins |
| `coro_transform.py` | 4,509 | `_FrameBuilder` (2,960 LOC / 98 methods) + 30 module fns |
| `codegen/` | 13,875 | `CodeGenerator` + **17** mixins |
| driver + support | 3,247 | `sawc.py` 1,268, `ast_dump` 671, `module_resolver` 462, `docs_emit` 430 |

### Port-cost hotspots (biggest functions)

```
867  typechecker/expressions.py:1997  _check_function_call
502  typechecker/expressions.py:5554  _check_method_call
461  codegen/calls.py:668             _generate_method_call
443  sawc.py:513                      _prepare_codegen
429  typechecker/registration.py:986  _register_extension
411  typechecker/core.py:806          check_module
402  coro_transform.py:4108           transform_program
```

Five of the seven are single functions larger than the entire ported lexer's
core loop. `_check_function_call` alone (867 lines) is roughly half the size of
the whole Saw lexer package.

### Dispatch and dynamism, counted

| Pattern | Count | Worst file |
|---|---:|---|
| `isinstance(...)` call sites | 879 | `coro_transform.py` (324), `typechecker/expressions.py` (131) |
| `isinstance` if/elif chains ≥4 arms | 30 | `ast_dump.py:337` (31 arms), `typechecker/expressions.py:7297` (25 arms) |
| `getattr(...)` | 666 | `coro_transform.py` (156) |
| attribute writes onto non-`self` objects | 398 | `typechecker/expressions.py` (132) |
| `id(...)` object-identity uses | 42 | `coro_transform.py` (17) |
| `raise` statements | 149 | 93 `ValueError`, 37 `CoroTransformError`, 12 `SyntaxError` |
| `except` handlers | 22 | 3 of them `except Exception` |
| `dataclasses.fields()` reflection | 12 | 11 in `coro_transform.py`, 1 in `typechecker/effects.py:51` |
| `copy.deepcopy` on AST | 16 | `typechecker/effects.py` (4), `core.py` (3), `coro_transform.py` (6) |

### One genuinely good baseline

`Parser` carries **12 `self` attributes, all assigned in `__init__`** — the only
stage in the compiler with no late-grafted state. Compare `TypeChecker` (52
attributes) and `CodeGenerator` (74). This is the single strongest argument for
the parser being the next port target (§4).

---

## 1b. Pass boundaries: what actually crosses

The advertised pipeline is lexer → parser → typecheck → coro_transform →
codegen. What each boundary *actually* carries:

| Boundary | Declared contract | What really crosses | Clean? |
|---|---|---|---|
| lexer → parser | `List[Token]` | `List[Token]` **plus** `lexer.doc_comments` trivia, passed separately (`sawc.py:38-39`) | **yes** — the only clean boundary; already frozen by `make lexdiff` |
| parser → typecheck | `Program` | `Program`, with `ImportDecl`/`ModuleDecl`/`ExportDecl`/`StaticAssert` living outside the `ASTNode` hierarchy (H16); doc text attached by string-keyed reflection (H16) | mostly |
| typecheck → coro/codegen | "the typed AST" (design 02) | the same `Program` object, now **mutated in place**: ~50 undeclared annotations grafted (H1), `Block.final_expr`/`type_args` structurally rewritten (H14), plus a `Namespace` that itself **holds AST references** (`namespace.py:223-226`) so the symbol table and the tree are one aliased graph (H12) | **no** |
| typecheck → coro_transform | — | additionally **nine typechecker side-effect tables** read via `getattr` (H8), three callbacks *into* the typechecker, and a `namespace` swap + write-back | **no** — bidirectional |
| coro_transform → driver | `bool` "changed" | `bool`, plus in-place mutation of the entry `Program`, plus a **full recursive re-run of the entire front half** including re-parsing all of `sawc/std/` (H8) | **no** — a fixpoint, not a pass |
| → codegen | `Program` + `Namespace` | those, plus codegen **writing llvmlite values back onto AST nodes** (H1(b)) | **no** |

`coro_transform` runs **after** typechecking, mutates the AST in place, and is
gated entirely on typechecker side-effect state — settled at `sawc.py:912-946`.
It is *source-level* in the sense that it emits ordinary Saw declarations rather
than IR (it never re-parses text — construction is pure AST-to-AST from the ~50
node classes imported at `coro_transform.py:32-49`), but it is *not* a
pre-typecheck desugaring: it requires `resolved_type` on 25 read sites and the
typechecker's effect graph, and performs no independent inference.

**Net:** exactly one of six boundaries is a clean data contract today, and it is
the one that has already been ported. That is not a coincidence — R1/R7/R11 exist
to give the next boundary the same property.

---

## 2. Port-hazard inventory

Each entry: **hazard → where → why it hurts a Saw port → Python-side
remediation.**

---

### H1 — 59 undeclared cross-pass AST annotations; the typed-AST contract is invisible

**Where.** `Expression` is an empty base (`sawc/ast_nodes.py:411-413`:
`class Expression(ASTNode): pass`). The typechecker's chokepoint stamps
`expr.resolved_type = result` at `sawc/typechecker/expressions.py:62` for every
expression — but `resolved_type` is a *declared* field on only **6 of the 44
`Expression` subclasses** (6 of 80 AST node classes overall)
(`ast_nodes.py:662, 689, 766, 785, 804, 828` — `NoneLiteral`,
`SourceLocationLiteral`, `OptionalWrap`, `ResultOkWrap`, `ResultErrWrap`,
`ErasedErrWrap`). The other 38 `Expression` subclasses receive it dynamically.

Beyond `resolved_type`, a probe found **59 attribute names that are written onto
AST nodes at runtime and never declared anywhere**. Representative writer→reader
pairs, all typechecker→codegen:

| attribute | writer | reader |
|---|---|---|
| `arg_plan` | `typechecker/expressions.py:1437,1451` | `codegen/calls.py:393,1106,1525,1578` |
| `resolved_symbol` | `typechecker/expressions.py:1897,1953,2615,6070,6124` | `codegen/calls.py:289`, `coro_transform.py:2064,3895,4228` |
| `existential_dispatch` | `typechecker/expressions.py:5248` | `codegen/calls.py:688` |
| `erased_box_make` / `erased_downcast` | `expressions.py:5364 / 5288` | `codegen/calls.py:686 / 698` |
| `matched_enum_type` / `matched_scrutinee_type` / `use_general_match` | `expressions.py:6527 / 6952 / 6951` | `codegen/match.py:48 / 329 / 33` |
| `um_projection` / `um_method` / `um_volatile` | `expressions.py:3652,3680 / 3725,3761 / 3696` | `codegen/structs.py:197`, `collections.py:162`, `calls.py:737,1251` |
| `error_type` / `error_types` / `erase_propagate` | `expressions.py:7589 / 7590 / 7506` | `codegen/results.py:270 / 271 / 192` |
| `is_chan_recv` | `expressions.py:6054` | `coro_transform.py:2051,2160,2180,4217` (8 reads) |
| `_coro_split` | `coro_transform.py:1346` | `coro_transform.py:1467,1817,2577` |

Four are dead: `um_use_name` (`expressions.py:3695`), `is_static_ref`
(`expressions.py:366`) and `type_args_inferred` (`expressions.py:1188`) are
written and never read; `synthesized_access` is **read at three sites**
(`expressions.py:3790, 3811, 4339`) with **no writer anywhere** — it always
defaults to `False`. A port would faithfully reproduce all four unless someone
notices.

**Why it hurts.** Saw has no dynamic attributes. Every one of these 59 must
become a declared field before a line of Saw is written — and today the only way
to enumerate them is a static-analysis probe. A porter who misses one gets a
compile error in Saw at best and a silently-missing codegen branch at worst.
Worse: the contract has no type. `arg_plan` is "some list of something"; its
shape lives only in the two call sites.

**Three aggravating sub-findings.**

*(a) The grafts are invisible to the compiler's own reflective walkers — and this
is a live bug, not just a port hazard.* `substitute_ast_types`
(`typechecker/effects.py:51-52`), the monomorphization type-substituter, iterates
`dataclasses.fields(node)`. Grafted attributes are not dataclass fields, so they
are **never type-substituted**. They *do* survive `copy.deepcopy`
(`effects.py:419, 535` — deepcopy copies `__dict__`), so every `SawType`-valued
graft is carried into an instantiation **stale**: `expected_type`,
`vector_container_type`, `spawn_result_type`, `um_scalar_type`,
`arc_forward_payload_type`, `box_forward_payload_type`, `matched_enum_type`,
`result_enum_type`, `error_type`/`error_types`. Declaring the fields (R1) makes
the substituter see them and fixes the class.

*(b) Codegen mutates the AST it is consuming.* Four grafts store **llvmlite
values on AST nodes** — `codegen_env_dtor` (`codegen/closures.py:244,305` →
`closures.py:316`, `calls.py:1321`), `_cg_closure_fn` (`closures.py:330` →
`calls.py:1319`), `_cg_env_value` (`closures.py:331` → `calls.py:1320`) — and
codegen self-stamps `resolved_type` at `codegen/collections.py:78,91`,
`codegen/core.py:2166`, `codegen/calls.py:493`. So codegen is not a read-only
consumer of a typed AST; it caches into it. Under Saw's ownership rules that
forces `&var Program` through the whole back end for what is really a side
table. Remediation: move these to a `Dict[NodeId, ...]` cache on the generator
(trivial once R2 lands).

*(c) `hasattr` as presence-signal, including three no-ops.* Five sites branch on
attribute *presence* rather than value — `codegen/structs.py:226`
(`resolved_module`), `typechecker/expressions.py:1287` (`autowrap_to_optional`),
`3886` (`resolved_module`), and `codegen/calls.py:783` (`resolved_enum_init`).
Three further `hasattr` checks on `resolved_init_params`
(`codegen/calls.py:349, 1623`, `expressions.py:2579`) are **unconditionally
true** because the field *is* declared (`ast_nodes.py:654`) — they silently
paper over the real `None`-vs-list distinction the field's own comment
documents. "Attribute exists" has no Saw analogue at all; every one of these must
become an explicit `Optional` test, and the three no-ops are latent bugs today.

**Remediation (Python, cheap).** Give `ASTNode` real base fields using
`@dataclass(kw_only=True)` (the repo is on Python 3.14, so the historical
"no default values to avoid inheritance issues" comment at `ast_nodes.py:404` no
longer binds — and today that comment costs **`line: int = 0` and
`column: int = 0` re-declared 80 times**, once per concrete node class, because
the base contributes zero fields). Declare `line`, `column`, `resolved_type` on the base; declare the
remaining 58 on the specific nodes that carry them, giving each a real type.
Group the clusters that always travel together into small records —
`CallPlan { arg_plan, resolved_symbol, existential_dispatch, is_field_call,
field_call_unwrap, arc_forward_payload_type, box_forward_payload_type }` hung off
`FunctionCall`/`MethodCall`; `MatchPlan` off `MatchExpr`; `UnsafeMemPlan` off the
UM nodes. Delete the nine write-only attributes. **This one change converts the
port's hardest unknown into a mechanical transcription.**

---

### H2 — Python object identity (`id()`) is load-bearing, and leaks into output

**Where.** 42 sites. The severe ones:

- **Effect graph.** `self._suspend_nodes: Dict[Any, SuspendNode]`
  (`typechecker/effects.py:112`) is keyed by a *heterogeneous* union documented
  at `effects.py:110-111`: `("fn", name)` tuples for free functions, `id(Method)`
  for methods (`effects.py:249`), `id(ClosureExpr)` for closures
  (`effects.py:275`). Read back at `sawc.py:344`, `coro_transform.py:4156,4318`.
- **Move checking.** `self.moved_bindings: Dict[int, ...]` keyed by
  `id(VariableInfo)` (`typechecker/core.py:120-125` — the comment explicitly
  reasons about `id()` reuse and keeps objects alive to prevent it).
- **Coroutine transform.** `call_by_id` / `recv_by_id` / `blk_by_id` keyed by
  `id(stmt)` (`coro_transform.py:1788,1794,1800`, read `2524,2530,2535`);
  extension identity sets `{id(e) for e in program.extensions}`
  (`coro_transform.py:4123`).
- **Generated names.** `union_name = f"_CatchError_{id(expr)}"`
  (`typechecker/expressions.py:7646`) — a **type name derived from a memory
  address**, which then flows into codegen (`codegen/results.py:579,610`) and is
  special-cased out of diagnostics (`ast_nodes.py:117-125`, whose own comment
  says "its non-deterministic id"). Same pattern for a codegen temp,
  `f"__collit_{id(expr)}"` (`codegen/collections.py:85`).

**Why it hurts.** Saw has no `id()`. There is no address-stable, hashable handle
for a value in an ownership language — and even in Python this is already a
correctness smell: **compiler output is not reproducible** across runs for any
program using multi-error `try/catch`. A port has to invent node identity
anyway; inventing it now also fixes a real determinism bug.

**Remediation.** Assign a monotonic `node_id: NodeId` in the parser (one counter
on `Parser`, already the cleanest state holder), declared on the `ASTNode` base
from H1. Rekey `_suspend_nodes` on a proper `EffectKey` sum
(`Fn(name) | Method(NodeId) | Closure(NodeId)`), rekey `moved_bindings`,
`call_by_id`/`recv_by_id`/`blk_by_id`, and change the two generated names to use
`node_id`. Sizeable win per unit of effort; the diff is mostly mechanical.

---

### H3 — Exceptions do three different jobs, two of which have no Saw analogue

**Where.** Three distinct uses, all `raise`/`except`:

1. **Speculative parsing (backtracking).** `parser/expressions.py:407-418`,
   `605-617`, and two more sites: save `self.pos`, `try: self._parse_type_args()`,
   `except SyntaxError: self.pos = saved_pos`. Four sites.
2. **Error recovery.** `parser/core.py:489-499` — `try: self._parse_toplevel_decl()`
   / `except SyntaxError: errors.append(str(e)); self._synchronize()`, capped at
   `MAX_PARSE_ERRORS`.
3. **Internal compiler errors.** 93 bare `raise ValueError` (codegen 76 of them:
   `calls.py` 21, `statements.py` 16, `types.py` 12, `operators.py` 11), funneled
   by exactly one `except Exception` in `run_codegen` (`sawc.py:504-509`) that
   prints `internal compiler error: {e}`. Plus 37 `raise CoroTransformError`
   (`coro_transform.py:51`) caught once at `sawc.py:928`.

**Why it hurts.** Saw has no exceptions — errors are `Result`/`Optional`. Use (1)
must become an explicit `Optional`-returning speculative parse; use (2) must
become an explicit error-return + resync; use (3) must become either a returned
`Result` or a `panic` (defensible for a genuine ICE, but 93 of them at arbitrary
depth means 93 decisions). Doing this *during* the port means restructuring
control flow and translating simultaneously.

**Remediation.** De-exception the parser first (it is small and self-contained):
add `_try(parse_fn) -> Optional[T]` that snapshots/restores `self.pos` without
raising, and make `_parse_toplevel_decl` return `Optional[Decl]` with the error
pushed to the reporter (see H4). Then the parser has **zero** exceptions and
ports 1:1. For codegen, replace `raise ValueError(msg)` with
`self._ice(node, msg)` — one helper, structured, located, and at port time it
becomes a single `panic` site instead of 93.

---

### H4 — Four diagnostic representations, not one funnel

**Where.**

| Producer | Representation | Located? |
|---|---|---|
| typechecker (452 calls to `reporter.error/_error`) | `CompilerError` dataclass w/ `SourceLocation` (`errors.py:44-49`) | yes, with snippet + caret |
| lexer (`lexer.py:225`), parser (`parser/core.py:176`) | `SyntaxError(f"Parse error at {line}:{col}: {msg}")` — location **baked into a string** | no; printed raw at `sawc.py:32-43` |
| codegen | `ValueError(str)` → `internal compiler error: {e}` | no |
| coro transform | `CoroTransformError(message, line, column, source_file)` → converted to `ErrorKind.TYPE_MISMATCH` at `sawc.py:932-935` | yes, via a translation shim |
| driver | 24 direct `sys.exit(1)` after `print(...)` | no |

**Why it hurts.** The Saw port needs *one* `Diagnostic` value type and *one*
sink. Today three of the five producers destroy structure (location becomes
prose), which means the port cannot mechanically translate them — it has to
re-derive where each error is anchored. It is also a user-facing quality gap:
**syntax errors get no source snippet or caret** while type errors do.

**Remediation.** Route lexer and parser through `ErrorReporter` (they already
know `line`/`column` at the raise site — `lexer.py:224`, `parser/core.py:174-176`
have the token in hand). Give `CoroTransformError` its own `ErrorKind` instead of
borrowing `TYPE_MISMATCH`. Replace driver `print`+`exit` with reporter calls.
End state: every diagnostic is a `CompilerError` and the port copies one type.

---

### H5 — Two mixin god-objects; Saw traits carry no stored state

**Where.** `CodeGenerator(ResultsMixin, MatchMixin, StructsMixin,
CollectionsMixin, CallsMixin, OperatorsMixin, StatementsMixin, MethodsMixin,
LoopsMixin, ConditionalsMixin, OptionalsMixin, ClosuresMixin, GenericsMixin,
ExistentialsMixin, TypesMixin, ResourcesMixin, DebugInfoMixin)` —
`codegen/core.py:99`, 17 bases, 2,410 lines in the core class alone.
`TypeChecker(ExpressionsMixin, StatementsMixin, RegistrationMixin,
TypeUtilsMixin, EffectsMixin)` — `typechecker/core.py:76`.

State is shared implicitly through `self`: **52 distinct attributes** on
`TypeChecker`, **74** on `CodeGenerator`. Mixins own their own sub-initializers
(`_effect_init` at `effects.py:110`, `_di_init` at `debuginfo.py:32`,
`_existential_init` at `existentials.py:38`) — i.e. each mixin declares *stored
state* on the composed object. Some attributes appear from nowhere mid-pass and
are read defensively: **61 `getattr(self, 'x', default)` sites**, e.g.
`getattr(self, '_checking_builtins', False)` (`typechecker/core.py:420,438`,
`statements.py:143,635`), `getattr(self, 'current_type_params', {})`
(`statements.py:73,152,527,653`), `getattr(self, '_raw_byte_globals', None)`
(`codegen/calls.py:428`), `getattr(self, '_need_result', True)`
(`codegen/core.py:2051`), `getattr(self, '_std_dir_prefix', None)`
(`typechecker/core.py:196`).

**Why it hurts.** Saw traits declare methods, not stored properties, and there is
no multiple inheritance. There is no direct translation of "17 classes that all
mutate the same 74 fields." The port target has to be **explicit context structs
+ free functions (or extension methods on the context)**, and the mixin
decomposition gives no guidance about which fields belong to which concern —
because nothing enforces it.

**Why it is not as bad as it looks.** The mixin split is already
concern-shaped, and the fields cluster naturally into three lifetimes:

- **Compilation-wide** (`namespace`, `module`, `triple`, `int_type`, `freestanding`,
  `functions`, `struct_types`, `enum_types`, the generic tables) — one `Unit` struct.
- **Per-function** (`builder`, `variables`, `variable_types`, `loop_stack`,
  `cleanup_stack`, `self_type_context`; typechecker side: `current_scope`,
  `current_function`, `current_method`, `loop_depth`, `loop_break_info`,
  `current_type_params`, `_unsafe_marker_depth`, `_current_fn_unsafe_domain`,
  `_ptr_cast_depth`) — a `FnCtx` that is already save/restored by hand at
  `typechecker/statements.py:73,142-152,634-653` and `codegen/core.py:2051-2060`.
- **Per-instantiation** (`type_param_context`, `current_type_subst`).

**Remediation.** Do not attempt the full context-struct rewrite in Python — it is
L-sized and low-yield there. Do the *cheap prefix*: (a) make the hand-rolled
save/restore pairs into an explicit `FnCtx` value that is pushed/popped as a
unit, which is the shape the port needs and is testable today; (b) move every
mixin sub-initializer's fields into the core `__init__` so the field set is
declared in one place (kills the 61 defensive `getattr(self, ...)` reads);
(c) write down the three-lifetime partition in `codegen/README.md` and
`typechecker/README.md`. That is enough to make the port's structural decision a
transcription rather than a redesign.

---

### H6 — Arbitrary-precision integers in the literal and const-eval paths

**Where.**

- `lexer.py:483` `value = int(digit_str, base)` and `:509` `ival = int(value)` —
  unbounded parse, *then* range-checked (`_check_int_range`). The Saw port must
  invert that: check *during* parse. (This was already hit by the lexer pilot —
  DF-116b, closed by design 119 Part A's `to_uint`.)
- `IntLiteral.value: int` (`ast_nodes.py:429`) is unbounded all the way to
  codegen: `expr.value & ((1 << width) - 1)` at `codegen/core.py:2081,2095`, and
  the platform-width guard `-(1 << (w-1)) <= expr.value < (1 << w)` at
  `codegen/core.py:2097`.
- Range tables hold values Saw's `Int` cannot represent:
  `TypeKind.UINT: (0, 18446744073709551615)` and
  `TypeKind.INT: (-9223372036854775808, ...)` (`typechecker/types.py:1455-1465`),
  `TypeKind.UINT64: (0, (1 << 64) - 1)` (`typechecker/expressions.py:4136`).
- **`_const_eval`** (`codegen/core.py:1527-1567`) evaluates `static_assert`
  expressions with unbounded Python `+ - * / %` and no width discipline at all.

**Why it hurts.** Saw's `Int` is 64-bit with overflow checks always on. A
`UInt64` literal at its maximum, or `Int.min`'s magnitude written positively,
simply does not fit; a direct transcription panics. `_const_eval` would panic on
any intermediate that overflows even where the final value fits.

**Remediation.** Model the literal the way the target can: `IntLiteral` carries a
`u64` magnitude plus the sign context (or the checked-parse result of design
119's `to_uint`), and the range tables become `(min_i64, max_u64)` pairs over
that representation. Make `_const_eval` evaluate at a declared width with
explicit wrap/trap, matching what Saw will do. Small, and it removes a whole
class of "works in Python, panics in Saw" surprises.

---

### H7 — `dataclasses.fields()` reflection and `deepcopy` in the coroutine transform

**Where.** 12 reflective traversals: 11 in `coro_transform.py` —
`326-327` (`_rewrite_node`), `1385`, `1606`, `1645`, `2245`, `3113-3114`, `3161`,
`3830-3831`, `3903-3904`, `3932`, `3965` — plus the type substituter
`substitute_ast_types` (`typechecker/effects.py:51`), which drives
monomorphization. They enumerate a node's fields
generically and `setattr` rewritten children back. Plus `copy.deepcopy` on AST at
16 sites (`coro_transform.py:1097,1148,1162,1172,1177,3956`;
`typechecker/effects.py:419,535,571,616`; `typechecker/core.py:1154,1169,1175`;
`typechecker/registration.py:970-972`).

**Why it hurts.** Saw has no runtime field reflection. Every one of those 12 sites
becomes a hand-written traversal over 80 node types — and if each is written
independently, that is 12 × 80 match arms with 12 chances to miss a node. The
`deepcopy` sites need an explicit recursive `clone()` per node type under Saw's
ownership rules; the typechecker's "pristine generic template" mechanism
(`effects.py:419` etc.) depends on it structurally.

**Remediation.** Add **one** generic traversal to `ast_nodes.py`:
`children(node) -> list[Node]` and `rewrite_children(node, f)`, generated once
(they can still use `dataclasses.fields` in Python — the point is that there is a
*single* definition to port). Convert all 11 sites to call it. Add `clone(node)`
alongside. In Saw these become three big `match`es written once, and Saw's
exhaustiveness checking turns "missed a node type" from a silent bug into a
compile error — a net *improvement* over the Python original.

---

### H8 — The pipeline is not a pass sequence; it is a fixpoint with bidirectional coupling

**Where.** `sawc.py:_prepare_codegen` (`sawc.py:513`, 443 lines) does: resolve
modules → parse → load+typecheck builtins → typecheck modules → merge namespaces
→ *maybe run the coroutine transform* → build codegen. The transform branch:

```python
driven = (getattr(typechecker, "_driven_roots", None)
          or getattr(typechecker, "_driven_method_roots", None)
          or getattr(typechecker, "_spawn_roots", None)
          or getattr(typechecker, "_main_suspends", False))       # sawc.py:919-922
...
changed = transform_program(entry_ast, typechecker, imported_ast=merged_ast)
if changed:
    return _prepare_codegen(source_path, entry_ast, entry_source, ...)  # sawc.py:943
```

The transform **mutates `entry_ast` in place** (`coro_transform.py:4504-4508`)
and the driver then **re-runs the entire front half recursively**, including
re-reading, re-lexing, re-parsing and re-type-checking `builtin.saw` **and every
file in `sawc/std/`** — `build_builtin_namespace` (`sawc.py:254`) has no cache.
The base case is that the rewrite deleted its own `__saw_drive` sites, so the
second pass finds nothing driven.

The coupling is not one-way. The transform:
- reads **nine** typechecker side-effect tables (`_driven_roots`,
  `_driven_method_roots`, `_spawn_roots`, `_mt_spawn_roots`, `_main_suspends`,
  `_suspend_nodes`, `_std_suspending_methods`, `_driven_generic_struct_methods`,
  `_entry_module_ns`) at `coro_transform.py:4005-4012, 4109-4128, 4151-4152, 4416`;
- **writes back** `typechecker._suspending_methods_set` (`coro_transform.py:4159`,
  read at `2053,2162,2182,4209`) — cross-instance state smuggled through the
  typechecker;
- **swaps** `typechecker.namespace = entry_ns` (`coro_transform.py:4015`) and
  restores it (`:4104`);
- **calls back into the typechecker** — `_splice_fn_mono`
  (`typechecker/effects.py:554`) fetched at `coro_transform.py:4006` and invoked
  mid-transform to monomorphize and splice new generic instantiations.

Also note `_std_suspending_methods` is injected *by the driver*
(`sawc.py:769-770`) from the builtin namespace — a table that travels
driver → typechecker → transform.

**Why it hurts.** The port cannot treat this as `check(ast) -> typed_ast` then
`transform(typed_ast) -> ast'`. It is a mutually-recursive cluster whose contract
lives in `getattr` defaults. Under Saw's ownership rules, "hand the transform a
mutable typechecker it will write back into while the driver still holds it" is
not expressible without deliberate `&var` plumbing that has to be designed, not
transcribed.

**Remediation, in two independently useful pieces.**
1. **Make the input explicit.** Have the typechecker produce a single
   `EffectSummary` value (the nine tables, named and typed) returned from
   `finalize_effects`. Change the signature to
   `transform_program(program, effects: EffectSummary, hooks: MonoHooks) -> Program`
   where `MonoHooks` is a tiny interface holding the three callbacks
   (`splice_fn_mono`, `resolve_type`, `get_enum_info`). Delete the namespace swap
   and the `_suspending_methods_set` write-back (thread it through
   `_FrameBuilder`'s constructor instead — it already takes `tc`).
2. **Cache the builtins.** `build_builtin_namespace` is deterministic per
   `(freestanding, runtime_build)`; memoize it. This halves front-end work for
   every concurrent program *today* and removes the "the recursion redoes std"
   surprise from the port's mental model.

Neither piece changes behavior; both make the boundary a data contract.

---

### H9 — `SawType` is a 20-field product standing in for a sum

**Where.** `ast_nodes.py:45-98` — one dataclass with `kind: TypeKind` plus 19
mostly-`Optional` fields, of which only 1-3 are meaningful for any given kind
(`element_types`, `tuple_field_names`, `struct_name`, `inner_type`, `enum_name`,
`type_args`, `type_param_name`, `array_element_type`, `array_size`,
`param_types`, `func_return_type`, `func_is_sync`, `func_is_escaping`,
`pointer_mutable`, `module_name`, `reference_mutable`, `existential_trait`,
`symbol: Optional[Any]`). Consumed by **607** `.kind ==` / `.kind in` tests
across the compiler.

**Why it hurts.** Transcribed literally into Saw this is a struct with 19
`Optional` fields where every access is a force-unwrap justified by an earlier
`kind` check — i.e. every type query is a latent panic, and the compiler cannot
help. The correct Saw shape is an enum with payload cases, which turns the 607
sites into `match`.

**Two facts make this cheaper than it looks.** (a) `SawType` is effectively
**immutable** — a grep for in-place field mutation finds exactly **two** sites
(`parser/types.py:139,141`, setting `func_is_sync`/`func_is_escaping` right after
construction). A value that is never mutated ports to a value enum directly.
(b) The `kind` tag already exists and is already the dispatch key, so the
conversion is mechanical rather than semantic.

**Remediation.** Do not convert to a sum in Python — that is an L-sized
high-risk churn with no Python-side payoff. Instead: (i) fix the two mutation
sites so `SawType` is constructed complete (then it is provably immutable);
(ii) add constructor functions (`SawType.struct(name, args)`,
`SawType.optional(inner)`, …) and predicate/accessor pairs
(`is_struct()`/`struct_name_of()`), and migrate the highest-traffic call sites.
The accessor layer is exactly the surface the Saw enum will expose, so migrated
sites port verbatim and un-migrated ones are visibly un-ported.

---

### H10 — Reflective `visit_*` dispatch that fails silently, replicated across five AST consumers

**Where.** Both chokepoints resolve handlers by string:

```python
method_name = f'visit_{expr.__class__.__name__}'
visitor    = getattr(self, method_name, None)
if visitor is None:
    return None                      # typechecker/expressions.py:56-59
```
```python
visitor = getattr(self, method_name, None)
if visitor is None:
    raise ValueError(f"Unknown expression type: {type(expr)}")   # codegen/core.py:2055-2057
```

Plus `visitor.py:26-33` (the unused generic base). Five separate consumers walk
the AST — `typechecker/`, `coro_transform.py`, `codegen/`, `ast_dump.py`,
`docs_emit.py` — each with its own hand-rolled dispatch. `ast_dump.py:337` is a
31-arm `isinstance` chain; `ast_dump.py` imports only ~45 of the 80 node classes
(`ast_dump.py:8-19`), so it is silently incomplete.

**Why it hurts.** The typechecker variant **returns `None` for an unhandled
node** — a new AST node type is not a compile error, not a runtime error, just a
missing type annotation that surfaces later as a confusing codegen ICE.

**Why the port is an improvement.** In Saw this becomes `match` over an AST enum,
and exhaustiveness is checked. Adding a node type would then break all five
consumers *at compile time* — which is what you want. This hazard is really a
**requirement**: the AST must port as one enum (or one enum per category:
`Expr`, `Stmt`, `Decl`, `Pattern`), not as 80 unrelated structs, or the benefit
is lost.

**Remediation (Python).** Nothing structural is needed, but two cheap things pay:
(a) make the typechecker chokepoint raise instead of returning `None` for an
unknown node (fail loud, like codegen already does); (b) fix `ast_dump.py` to
cover all node types — it is the natural differential-harness oracle for the
parser port (§4) and cannot be one while incomplete.

---

### H11 — Untyped tuple records and nested string-keyed dicts as data structures

**Where.** Codegen state (`codegen/core.py:199-252`):

```python
self.struct_types: dict = {}          # name -> (LLVM type, field_order)
self.enum_types:   dict = {}          # name -> (LLVM type, variant_tags, variant_info)
self.loop_stack: List[tuple] = []     # (continue_block, break_block, result_storage)
self.pending_method_bodies: List[tuple] = []   # (mangled_struct_name, method, type_mapping, is_init)
self.specialized_extensions: dict[tuple, List[Extension]] = {}   # (struct, type_args) -> ...
self.plain_generic_methods: dict[str, dict[str, Method]] = {}
```

and in the namespace, `self.conformances: Dict[str, Dict[str, Dict[str, SawType]]]`
(`namespace.py:220`) — a three-level string dict whose meaning exists only in a
comment. Also `typechecker/core.py:152`
`_export_symbol_table: Dict[str, Tuple[str, int, int, Optional[str]]]` and
`effects.py:128,137` `Dict[str, Any]`.

**Why it hurts.** Saw has no anonymous heterogeneous tuples-as-records culture
and no `Any`. Each of these becomes a named struct at port time — fine — but the
*field names and types* have to be reverse-engineered from usage sites, and
`Dict[str, Any]` erases them entirely.

**Remediation.** Promote each to a small dataclass (`StructLayout`, `EnumLayout`,
`LoopFrame`, `PendingBody`, `Conformance`). Purely mechanical, no behavior
change, and it is exactly the Saw declaration. Note `namespace.py` already does
this well for symbols (9 typed symbol dataclasses at `namespace.py:33-189`) —
this is finishing a job the codebase already started.

---

### H12 — AST nodes are aliased and mutated across module boundaries

**Where.** `merge_programs` (`sawc.py:151`) merges module ASTs by **reference**,
so a `Method` object is reachable from both the entry program and an imported
one — the coroutine transform documents this explicitly at
`coro_transform.py:4115-4122, 4397-4403` and works around it with identity sets
(`_entry_ext_ids`, `coro_transform.py:4123`). The `Namespace` additionally holds
AST references (`generic_functions: Dict[str, Function]`,
`generic_structs`, `generic_enums`, `generic_extensions` —
`namespace.py:223-226`), so the symbol table and the AST are one aliased graph.
The `_pristine_*` tables (`effects.py:137,147,155`) keep `deepcopy`ed snapshots
precisely because the originals get mutated.

**Why it hurts.** This is the deepest hazard, because Saw's whole point is that
this is not expressible. "One `Method` object, two owners, mutated by a third
pass" needs either `Arc`/index-handles or a redesign where passes *produce* new
trees instead of editing shared ones.

**Remediation (scoping, not fixing).** Do not try to make Python's AST
single-ownership. Instead, **write down the sharing graph** so the port can make
one deliberate decision: an arena of nodes addressed by `NodeId` (which H2
already introduces) is the obvious target, and `NodeId` handles make aliasing
legal and explicit. Concretely in Python: change `Namespace`'s four generic
tables to store `NodeId` instead of node references and look up through an arena.
That is M-sized and can wait, but H2's `NodeId` should be introduced with this
end state in mind.

---

### H13 — Mutable mode flags toggled and restored mid-pass

**Where.** `namespace.allow_all_access` (`namespace.py:235,306,366,370`) is a
visibility kill-switch saved/restored around builtin checking at
`typechecker/statements.py:142-145, 341` and `634-637`, and set by the driver at
`sawc.py:273`. Similarly `_checking_builtins` (`sawc.py:277`,
`typechecker/core.py:420,438`), `_need_result` (`codegen/core.py:2051-2060`),
`_unsafe_marker_depth` / `_ptr_cast_depth` (`typechecker/core.py:105-112`),
`in_try_catch_block` (`typechecker/core.py:142`).

**Why it hurts.** These are dynamic-scope variables implemented by hand. Under
Saw's exclusivity rules, mutating a flag on a shared context while a nested call
reads it is legal but fragile, and the save/restore discipline (currently
correct-by-convention) has no enforcement. Missing a restore is a silent
mis-compile.

**Remediation.** Fold each into the `FnCtx` value from H5 so a scope entry
*constructs* a new context rather than mutating and restoring a shared one. The
port then gets value semantics for free.

---

### H14 — "typecheck" is also an in-place desugaring pass

**Where.** The typechecker **rewrites the tree** while checking it. `Block.final_expr`
(a declared field, `ast_nodes.py:1197`) is reassigned to insert `ResultOkWrap` /
`ResultErrWrap` / `OptionalWrap` desugarings at
`typechecker/expressions.py:2924, 2931, 2939, 2946, 2965, 2980, 2993, 3002, 6690,
6706, 6773` and `typechecker/statements.py:284, 292, 321, 421, 429, 460`; the
coroutine transform later nulls it at `coro_transform.py:1188, 1723, 1729, 1734,
1741`. `type_args` is likewise reassigned post-parse at
`typechecker/expressions.py:956, 1021, 1184, 2375, 2635, 4258, 5419, 5947` and
`coro_transform.py:4045`. `MatchExpr.matched_expr` is rewritten at
`coro_transform.py:682, 3317`.

**Why it hurts.** The pass boundary advertised by design 02 is "the typechecker
annotates; codegen reads annotations." That is only half true — the typechecker
also *mutates structure*. A porter reading the README will build
`check(ast) -> annotations` and then discover that codegen depends on tree edits
that were never in the contract. Combined with H12 (nodes aliased across
modules) and H1(b) (codegen writes back too), **no pass in this compiler owns its
input**, which is precisely the property Saw's ownership model refuses.

**Remediation.** Do not un-mix it in Python — the auto-wrap desugaring genuinely
needs type information, so it belongs after inference. Instead **name it**: split
`check_module` into a `check` phase and an explicit `desugar` phase that runs on
the checked tree and returns the rewritten one, and document the tree edits in
`typechecker/README.md` alongside the annotation list from R1. The port then has
four honest stages (parse → check → desugar → transform) instead of three
advertised ones and a surprise.

---

### H15 — Module-level monkeypatching of a third-party library, guarded by a global flag

**Where.** `codegen/core.py:59-95`, `_install_volatile_ir_support()` — rebinds
`llvmlite.ir.instructions.LoadInstr.descr` and `StoreInstr.descr` at import time
so a per-instruction `.volatile` attribute is spliced into the rendered IR text,
guarded by a `_saw_volatile_patched` flag **stamped onto llvmlite's own class**
(`codegen/core.py:95`). The patched attribute is written at
`codegen/calls.py:1261, 1273` and read back at `codegen/core.py:79, 87` via
`getattr(self, "volatile", False)`.

Related driver-level grafting onto non-AST objects: `sawc.py:329-330` writes
`_std_file_symbols` / `_std_symbol_file` onto the builtin `Namespace` (whose
hand-written `__init__` at `namespace.py:191` declares neither), and `sawc.py:774`
writes `_std_symbol_file` onto the `TypeChecker`; read at
`typechecker/core.py:340, 424, 444` and `typechecker/expressions.py:2532, 4228,
5699`.

**Why it hurts.** Neither has a Saw analogue: you cannot add a field to someone
else's type at runtime, and there are no import-time side effects on shared
mutable class objects. Both are also invisible to anyone reading the type
definitions.

**Remediation.** Carry `volatile` in the generator's own side table keyed by
instruction, or upstream it. Declare the two `_std_*` tables as real fields on
`Namespace` and `TypeChecker` (they are part of the design-82 prelude mechanism,
not debug scaffolding) — one line each.

---

### H16 — String-keyed reflection over the `Program` declaration lists

**Where.** `parser/core.py:76-77` defines
`DOC_DECL_LISTS = ("functions", "structs", "enums", "traits", "extensions",
"type_definitions", "statics")`, and `parser/core.py:363-366` attaches doc
comments by `getattr(program, list_name)[-1].doc = block.text`. Separately,
`ImportDecl` (`ast_nodes.py:351`), `StaticAssert` (`:366`), `ModuleDecl` (`:378`)
and `ExportDecl` (`:389`) are **top-level declarations that are not `ASTNode`
subclasses** at all.

**Why it hurts.** The doc attachment works today only because all seven named
lists happen to hold classes that declare `doc` — nothing enforces it. In Saw
this needs a `Documentable` trait (or a `Decl` enum case), which means the port
has to decide the declaration hierarchy up front. The four non-`ASTNode`
declaration types will fight any clean `Decl` enum.

**Remediation.** Make the four stragglers `ASTNode` subclasses, and replace the
string-list reflection with an explicit `program.documentable_decls()` returning
a typed sequence. Both are small and both remove a decision from the port.

---

## 3. Ranked restructuring recommendations

Ordered by **payoff-per-effort for the port**. Each is shaped to become a
self-contained design brief. Sizes: **S** ≈ one focused session, **M** ≈ a
multi-commit brief, **L** ≈ a design decision plus a brief.

---

### R1 — Declare the cross-pass AST contract *(S/M, highest payoff)*
**Hazards:** H1, partly H10.
Make `ASTNode` a `kw_only` dataclass base with `line`, `column`, `node_id`,
`resolved_type` (removing 80 duplicate `line`/`column` declarations). Promote all
59 grafted attributes to declared, typed fields, grouping the co-travelling
clusters into `CallPlan` / `MatchPlan` / `UnsafeMemPlan` records. Delete the four
dead ones. Convert `getattr(node, 'x', default)` reads to direct field access and
the five `hasattr` presence-tests to explicit `is None` tests. Move codegen's
three llvmlite-value caches off the AST into a `Dict[NodeId, ...]`.
**Port payoff:** the port's single biggest unknown — "what fields does a node
actually have?" — becomes a file you read instead of a probe you write. Nothing
else on this list is worth as much per hour.
**Bonus — it fixes a live bug class.** `substitute_ast_types`
(`typechecker/effects.py:51`) walks `dataclasses.fields()` and therefore cannot
see grafted attributes, so every `SawType`-valued graft survives
monomorphization **un-substituted** (§H1(a)). Declaring the fields makes the
substituter see them. Also unmasks three unconditionally-true `hasattr` checks on
`resolved_init_params`.
**Risk:** low; the suite is the oracle and `--emit-ast` catches shape changes.
Expect the substituter to start firing on paths it previously skipped — that is
the fix, and monomorphization tests are the check.

### R2 — Stable `NodeId`; eliminate `id()` *(S)*
**Hazards:** H2, prerequisite for H12.
Parser assigns a monotonic id. Rekey `_suspend_nodes` (behind an `EffectKey`
sum), `moved_bindings`, the coro transform's three `*_by_id` maps, and the two
`id()`-derived generated names.
**Port payoff:** removes a construct Saw cannot express at all, from 42 sites.
**Bonus:** fixes non-deterministic compiler output for `try/catch` programs — a
real bug, worth doing on its own merits.

### R3 — One diagnostic funnel *(M)*
**Hazards:** H4, part of H3.
Lexer + parser + driver report through `ErrorReporter`; location stops being
prose; `CoroTransformError` gets its own `ErrorKind`; codegen's 93
`raise ValueError` become `self._ice(node, msg)`.
**Port payoff:** one `Diagnostic` type and one sink to port instead of four
representations and a translation shim.
**Bonus:** syntax errors gain the snippet+caret rendering type errors already have.

### R4 — De-exception the parser *(S/M)*
**Hazards:** H3 (uses 1 and 2).
Explicit `_speculate(...) -> Optional[T]` for the four backtracking sites;
`_parse_toplevel_decl -> Optional[Decl]` + resync for recovery. Depends on R3 for
where the errors go.
**Port payoff:** makes the parser exception-free, which is the precondition for
porting it (§4). After this the parser is a pure `tokens -> Result<Program>`
function with 12 fields of state — genuinely transcribable.

### R5 — One generic AST traversal + `clone` *(S)*
**Hazards:** H7.
`children(node)`, `rewrite_children(node, f)`, `clone(node)` defined once in
`ast_nodes.py`; the 11 `dataclasses.fields()` sites in `coro_transform.py` and
the 16 `deepcopy` sites call them.
**Port payoff:** 11 reflective traversals collapse to 1 hand-written `match`
instead of 11. Highest leverage available on the hardest file.

### R6 — Typed records for pass state *(S)*
**Hazards:** H11.
`StructLayout`, `EnumLayout`, `LoopFrame`, `PendingBody`, `Conformance`;
`Dict[str, Any]` in `effects.py` gets real types.
**Port payoff:** each becomes a Saw struct verbatim. Zero-risk, zero-behavior.

### R7 — Explicit effect summary; break the coro fixpoint's back-edges *(M)*
**Hazards:** H8.
`finalize_effects() -> EffectSummary`; `transform_program(program, effects,
hooks) -> Program`; delete the `typechecker.namespace` swap and the
`_suspending_methods_set` write-back; memoize `build_builtin_namespace`.
**Port payoff:** turns a mutually-recursive cluster into two functions with a
declared interface — the difference between "port it" and "redesign it".
**Bonus:** the memoization halves front-end work for every concurrent program.

### R8 — `FnCtx`: make the per-function scope a value *(M)*
**Hazards:** H5 (cheap prefix), H13.
Collect the hand-rolled save/restore sets in `typechecker/statements.py:73,
142-152, 634-653` and `codegen/core.py:2051-2060` into one pushed/popped context
value; move every mixin sub-initializer's fields into the core `__init__` so the
61 `getattr(self, ...)` defensive reads disappear.
**Port payoff:** establishes the "context struct + free functions" shape the Saw
port must use, incrementally and testably, without attempting the full
de-mixining.

### R9 — `SawType` accessor layer *(M)*
**Hazards:** H9.
Fix the two mutation sites; add constructors + predicate/accessor pairs; migrate
high-traffic `.kind ==` sites. Do **not** convert to a sum in Python.
**Port payoff:** the accessor surface is the Saw enum's surface, so migrated
sites port verbatim; the remaining `.kind` sites are a visible to-do list.

### R10 — Width-honest integer literals and const-eval *(S)*
**Hazards:** H6.
`IntLiteral` carries a bounded magnitude + sign; range tables expressed over it;
`_const_eval` evaluates at a declared width with explicit wrap/trap.
**Port payoff:** removes the "works in Python, panics in Saw" class from the two
places it is guaranteed to bite. Small, and the lexer pilot already proved the
pattern (design 119 `to_uint`).

### R11 — Complete and freeze `ast_dump.py` as a canonical AST dump *(S)*
**Hazards:** H10; enabler for §4.
Cover all 80 node types (it currently imports ~45), pin the format in a README
the way `selfhost/lexer/README.md` pins the token dump, and add
`tools/astdiff.py` + `make astdiff` mirroring `lexdiff`.
**Port payoff:** this is the **acceptance harness for the parser port**. Without
it the next port stage has no oracle; with it the bar is "zero mismatches over
842 examples + 162 error examples", exactly as the lexer had.

### R12 — Name the desugaring phase *(S)*
**Hazards:** H14.
Split `check_module` into `check` + an explicit `desugar` step that consumes the
checked tree and returns the rewritten one; document the structural edits
(`Block.final_expr` auto-wrap insertion, `type_args` rewriting) in
`typechecker/README.md` next to the R1 annotation list.
**Port payoff:** the port's stage list becomes honest — parse → check → desugar →
transform → codegen — instead of three advertised stages plus an undocumented
tree rewrite discovered mid-port.

### R13 — Declaration-hierarchy and library-hygiene cleanups *(S)*
**Hazards:** H15, H16.
Make `ImportDecl`/`StaticAssert`/`ModuleDecl`/`ExportDecl` `ASTNode` subclasses;
replace `DOC_DECL_LISTS` string reflection with a typed
`program.documentable_decls()`; declare `_std_file_symbols`/`_std_symbol_file` as
real fields on `Namespace`/`TypeChecker`; move the llvmlite `volatile`
monkeypatch (`codegen/core.py:59-93`) into a generator-owned side table.
**Port payoff:** removes three constructs with no Saw analogue (runtime field
addition on a foreign type, import-time global mutation, string-keyed
reflection over a struct's fields) and settles the `Decl` hierarchy the port's
AST enum needs.

**Suggested brief sequencing.** R1 → R2 → R11 → R4 (needs R3 for error routing,
so R3 can run in parallel or just before) → R5, R6, R10, R13 (independent, any
order) → R12 → R7 → R8 → R9. R1/R2/R11/R3/R4/R13 together are the "parser port
unblocked" set.

---

## 4. Port order: what comes after the lexer

**Next stage: the AST + the parser.** Not the typechecker, not codegen.

**Why the parser.**

1. **It is the only stage with clean state.** 12 `self` attributes, all assigned
   in `__init__`, zero late-grafted fields — versus 52 on `TypeChecker` and 74 on
   `CodeGenerator`. It is the only stage that is already close to "a struct and
   some methods."
2. **It is the smallest remaining front-end stage.** 3,929 LOC against 15,174
   (typechecker) and 13,875 (codegen). At the pilot's ~2.2× LOC ratio that is a
   tractable Saw package; the typechecker is not.
3. **Its input contract is already frozen and differentially tested.** The token
   stream is pinned by `make lexdiff` at zero mismatches over the whole corpus.
   The parser port consumes exactly that — it can even consume the *dump*
   initially, which design 116 deliberately left open ("the library API should
   merely not preclude linking").
4. **Its output oracle already half-exists.** `ast_dump.py` emits a canonical
   text AST; R11 completes it and `make astdiff` becomes the acceptance bar with
   the same shape and the same corpus as `lexdiff`. No other stage has a
   ready-made oracle — the typechecker would need a typed-AST dump invented from
   scratch, and codegen's oracle (IR text) is unstable across LLVM versions.
5. **It is the second-most-stable layer.** Design churn lives in the typechecker
   and above; the token grammar and the surface syntax have barely moved across
   121 designs. A parser port will not rot.
6. **It front-loads the shared artifact.** Porting the parser forces the AST data
   model into Saw — 80 node types as `Expr`/`Stmt`/`Decl`/`Pattern` enums with
   payloads. Every later stage needs that model, so building it now converts a
   one-time cost into a dependency every subsequent stage inherits. It is also
   where Saw's exhaustive `match` starts paying: the five hand-rolled dispatchers
   become checked.

**Prerequisites, in Python, before writing Saw** (all from §3):
R1 (declared fields — the Saw AST cannot be written without them),
R4 + R3 (exception-free parsing with structured errors),
R2 (`node_id`, since the Saw AST will need identity anyway),
R11 (the astdiff harness — the bar).
R5's `children`/`clone` should land too, since the Saw AST wants them from day one.

**Explicitly not next.**
- **`coro_transform.py` should be ported LAST**, after R5 and R7. It combines
  every hard hazard: 11 reflective traversals, 324 `isinstance` sites, 17 `id()`
  uses, a 2,960-line class, reentrant callbacks into the typechecker, and an
  in-place mutation contract with a whole-front-end re-run. Porting it before its
  interface is a data contract means designing rather than translating.
- **The typechecker** is the largest stage, carries the most design churn (so a
  port rots fastest), and has the most hidden state. It should follow the parser,
  and only after R8 has established the context-struct shape.
- **Codegen** is bound to llvmlite; a Saw port needs an LLVM-C binding decision
  that is a separate design question from anything in this review.

**Full suggested sequence:**
lexer *(done)* → **AST model + parser** → `namespace.py` (symbol table — already
the best-typed module in the compiler, 9 typed symbol dataclasses, and it is what
the typechecker needs first) → typechecker → codegen → coroutine transform.

---

## 5. Appendix — probe scripts

Reproduce the counts in this report:

```
.build/scratch/probe_crev_static.py   # raises/excepts, isinstance chains, grafting, globals, sizes
.build/scratch/probe_crev_state.py    # per-composed-class self-attribute inventory
.build/scratch/probe_crev_graft.py    # the 59-attribute cross-pass annotation contract
```

Run with `./.venv/bin/python <path>`.
