"""Generic TIER REQUIREMENTS — inference at the definition, discharge at the
call (design 219 wave C, the DF-217i fix).

A generic body used to be judged once with `T` abstract, and abstract `T`
answered every copy-tier question most permissively: `_check_value_transfer`
saw tier `'abstract'`, matched none of its arms, and fell off the end. Nothing
re-judged the body at instantiation, so `let a = sink(x); let b = sink(x)` at a
NoCopy argument compiled into three releases of one value (sweep S1 row 1) and
at an ExplicitCopy argument into a bitwise duplicate of a `Vector` (row 9d).

THE MODEL, in two rungs and one funnel.

  * The body is walked ONCE, while it is being typechecked anyway, and each of
    its type parameters comes out carrying a REQUIREMENT: `move` (the bottom —
    the body never duplicates a `T`, so every tier including NoCopy satisfies
    it) or `copy` (the body duplicates a `T` with nothing written at the site,
    so only the silent `Copy` tier satisfies it).
  * Each CALL SITE discharges the callee's requirement against the argument's
    DERIVED tier, with the refusal anchored at the caller's line and naming
    the reason the requirement exists.

The middle rung — `ExplicitCopy` — is deliberately absent: a spelled `.copy()`
demands a DECLARED `<T: ExplicitCopy>` (that gate lives in `_check_copy_call`),
because the tier that asks for ceremony per use asks for a contract per
signature.

WHY THE MOVE CHECKER IS THE INFERENCE (obligation 1's funnel).

The question "does this body duplicate a `T`, or merely move it?" is the
question design 15's move dataflow already answers, flow-sensitively, with
branch merges (`_merge_move_branches`), loop-carried detection
(`_check_loop_body`) and per-binding identity. So an abstract-tier transfer of
a whole owned binding marks that binding moved-from PROVISIONALLY, and the
requirement is inferred from what the existing checker does next:

  * nothing uses the binding again      -> the transfer WAS a move   (`move`)
  * some later use on the same path     -> it was a duplicate        (`copy`)

That is what makes `if a < b { b } else { a }` stay move-only — the two reads
are branch-exclusive, so neither is a second use, and the merge says so
without this module knowing what an `if` is. A PROJECTION read (`self.value`,
`t.0`, `p[i]`) never gets the benefit of the doubt: partial moves do not exist
(design 35), so the source keeps its copy and the requirement is `copy` on the
spot.

ENTRY POINTS (the four sites that can raise a requirement, all of them
existing chokepoints — this module adds no fifth walk of the AST):

  1. `_check_value_transfer` (types.py) — THE transfer checkpoint. Tier
     `'abstract'` + an aliasing source: a whole-binding read marks the
     provisional move, a projection notes `copy` directly.
  2. `_check_identifier` (expressions.py) — the use-after-move gate. A use of
     a provisionally-moved binding notes `copy` instead of erroring.
  3. `_check_move_expr` (expressions.py) — a spelled `move` of a
     provisionally-moved binding, same reading.
  4. `_check_loop_body` (registration.py) — a provisional move that survives to
     the next iteration is a second use of the same binding.

DISCHARGE ENTRY POINTS (`_tier_record_obligation`'s callers): the free-function
generic path and `_check_type_param_bounds` (which serves the overloaded,
module-qualified, method and static-method paths), plus the generic-struct
instantiation loop and the method path's receiver type arguments. Discharge is
DEFERRED to `_tier_discharge_all` at finalize for two reasons: a call may be
checked before the callee's body (declaration order is not call order), and a
requirement PROPAGATES — a generic that forwards its own `T` to a `copy`-
requiring callee acquires the requirement itself, which is a fixpoint.
"""

from typing import Dict, List, Optional, Tuple

from ast_nodes import Expression, Identifier, SawType, TypeKind
from errors import ErrorKind


# The requirement lattice. Two rungs, ordered.
REQ_MOVE = 'move'
REQ_COPY = 'copy'
_REQ_ORDER = {REQ_MOVE: 0, REQ_COPY: 1}

# The bound spellings that DECLARE the silent tier at a type parameter. A
# declaration covering the inferred requirement makes the requirement a
# contract rather than an inference (the API-stability mitigation).
_SILENT_BOUNDS = frozenset({"Copy"})

# Every copy-family bound spelling. A parameter carrying one of these has said
# something about duplication, so the coverage check has a declaration to
# measure the body against; a parameter carrying only e.g. `Comparable` has
# declared nothing about copying and rides pure inference.
_COPY_FAMILY_BOUNDS = frozenset({"Copy", "ExplicitCopy"})


class TierRequirementsMixin:
    """Requirement inference + call-site discharge. See the module docstring."""

    # ------------------------------------------------------------------
    # Definition side: the accumulator around one declaration's body.
    # ------------------------------------------------------------------

    def _tier_req_enter(self, decl_node, type_param_names) -> tuple:
        """Open a requirement accumulator for `decl_node`'s body.

        Returns the saved outer state for `_tier_req_exit`. Nesting is real —
        a generic method of a generic extension is checked inside the
        extension's scope — so the accumulator stacks like every other
        per-declaration checker state.
        """
        saved = (getattr(self, '_tier_req_acc', None),
                 getattr(self, '_tier_req_decl', None))
        if not type_param_names:
            # Not generic: no accumulator, and `_tier_req_note` becomes a no-op
            # for this body. A CLOSURE inside a generic body keeps the
            # enclosing accumulator, which is right — its captures and reads
            # are the enclosing function's duplications.
            self._tier_req_acc = None
            self._tier_req_decl = None
            return saved
        self._tier_req_acc = {}
        self._tier_req_decl = decl_node
        return saved

    def _tier_req_exit(self, decl_node, saved: tuple, type_param_names):
        """Close the accumulator and stamp the result on the declaration.

        The requirement is stored on the AST node (a declared annotation) so it
        travels with the std cache, which pickles the builtin AST and namespace
        together — a side table keyed by object identity would be empty on a
        cache hit and the diagnostics would depend on whether the cache was
        warm.
        """
        acc = getattr(self, '_tier_req_acc', None)
        if acc is not None and decl_node is not None:
            merged = dict(getattr(decl_node, 'tier_requirements', None) or {})
            for name in type_param_names:
                if name in acc:
                    merged[name] = acc[name]
                elif name not in merged:
                    merged[name] = (REQ_MOVE, "", 0)
            decl_node.tier_requirements = merged
        (self._tier_req_acc, self._tier_req_decl) = saved

    def _tier_req_note(self, saw_type: Optional[SawType], reason: str, line: int):
        """Record that the body duplicates a value of `saw_type` unwritten.

        Every abstract type parameter the type NAMES acquires the `copy`
        requirement: duplicating a `(T, Int)` or a `Wrap<T>` duplicates its
        `T`, and the tier of either is exactly the join of its members'.
        """
        acc = getattr(self, '_tier_req_acc', None)
        if acc is None or saw_type is None:
            return
        for name in self._tier_abstract_params_in(saw_type):
            prev = acc.get(name)
            if prev is not None and _REQ_ORDER[prev[0]] >= _REQ_ORDER[REQ_COPY]:
                continue
            acc[name] = (REQ_COPY, reason, line)

    # design 219 wave C carried a SECOND accumulator here — `_tier_cmp_acc`,
    # which recorded "this body compares a value of `T`" so the one discharge
    # point could run DF-216b's transitive walk on the concrete type ARGUMENT
    # (conformance row C07). Design 239 deleted it with the stopgap it served:
    # `Equatable`/`Comparable` take `other: &Self`, so a generic body comparing
    # its `T` transfers nothing and there is no requirement to record, forward
    # or discharge. The copy-tier accumulator below is untouched — that rule is
    # about DUPLICATION, which comparison never asked for.

    def _tier_abstract_params_in(self, saw_type: Optional[SawType],
                                 depth: int = 0) -> List[str]:
        """Every in-scope type-parameter name `saw_type` names, outermost first.

        Only parameters of the declaration currently being checked count: a
        `Vector<Int>` names none, and a concrete type reached through an alias
        names none either.
        """
        if saw_type is None or depth > 12:
            return []
        env = getattr(self, 'current_type_params', None) or {}
        out: List[str] = []

        def visit(t, d):
            if t is None or d > 12:
                return
            if t.kind == TypeKind.STRUCT and t.struct_name in env:
                if t.struct_name not in out:
                    out.append(t.struct_name)
                return
            for sub in (t.type_args or []):
                visit(sub, d + 1)
            visit(getattr(t, 'inner_type', None), d + 1)
            visit(getattr(t, 'array_element_type', None), d + 1)
            for sub in (getattr(t, 'element_types', None) or []):
                visit(sub, d + 1)

        visit(saw_type, depth)
        return out

    def _tier_binding_is_owned(self, expr: Expression) -> Optional[object]:
        """The `VariableInfo` a whole-binding transfer reads, or None.

        None means "this read cannot be a move": a projection, an unresolvable
        name, or a binding held BY REFERENCE (`&T` parameter, `&self`), where
        the referent belongs to the caller and reading it out is a duplicate no
        matter how many times the name appears.
        """
        if not isinstance(expr, Identifier):
            return None
        scope = getattr(self, 'current_scope', None)
        if scope is None:
            return None
        var_info = scope.lookup(expr.name)
        if var_info is None:
            return None
        vtype = getattr(var_info, 'type', None)
        if vtype is not None and vtype.kind == TypeKind.REFERENCE:
            return None
        return var_info

    def _tier_req_transfer(self, expr: Expression, src_type: SawType,
                           line: int, column: int,
                           is_return: bool = False) -> None:
        """The `'abstract'` arm of `_check_value_transfer` (entry point 1).

        A whole-binding read is PROVISIONALLY a move — design 15's dataflow
        decides, by whether anything uses the binding again. Anything else is a
        duplicate the moment it is written.
        """
        if getattr(self, '_tier_req_acc', None) is None:
            return
        if is_return and isinstance(expr, Identifier):
            # A RETURN of a whole binding is the last read on its path by
            # construction, so it is a move and raises nothing. Stated here
            # rather than left to the dataflow because the tail-expression
            # check runs after `_check_block` has popped the body scope: the
            # name no longer resolves, and every generic returning a local
            # would otherwise look like a read out of storage it does not own.
            # (`SpinLock.lock`'s `let result = body(...)` / `result` is the
            # shape, and it is the whole of std's generic return idiom.)
            return
        var_info = self._tier_binding_is_owned(expr)
        if var_info is None:
            self._tier_req_note(
                src_type,
                f"it reads `{self._tier_render(expr)}` out of storage it does "
                f"not own", line)
            return
        self._mark_binding_moved(var_info, expr.name, line, column,
                                 provisional=True)

    def _tier_req_second_use(self, var_info, name: str, use_line: int,
                             first_line: int) -> None:
        """A use of a provisionally-moved binding (entry points 2, 3 and 4).

        The first read was not a move after all, so the body needs a real
        duplicate — and the two lines are exactly what the refusal at the call
        site quotes.
        """
        vtype = getattr(var_info, 'type', None)
        if first_line and first_line != use_line:
            where = f"at lines {first_line} and {use_line}"
        else:
            where = f"at line {use_line}"
        self._tier_req_note(vtype, f"it binds `{name}` twice, {where}",
                            first_line or use_line)

    @staticmethod
    def _tier_render(expr: Expression) -> str:
        """A short rendering of a transfer source, for the requirement reason."""
        from ast_nodes import ArrayIndex, MemberAccess, TupleIndex
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, MemberAccess):
            return f"{TierRequirementsMixin._tier_render(expr.object)}.{expr.member}"
        if isinstance(expr, TupleIndex):
            return f"{TierRequirementsMixin._tier_render(expr.tuple_expr)}.{expr.index}"
        if isinstance(expr, ArrayIndex):
            return f"{TierRequirementsMixin._tier_render(expr.array_expr)}[…]"
        return "the value"

    # ------------------------------------------------------------------
    # The `.copy()`-needs-a-bound funnel (DF-217q).
    # ------------------------------------------------------------------

    def _tier_unbounded_copy_params(self, saw_type: Optional[SawType]
                                    ) -> List[str]:
        """The type parameters a `.copy()` on `saw_type` would reach that no
        copy-family bound covers — THE funnel for the declared-`ExplicitCopy`
        rule, over EVERY receiver shape (DF-217q).

        The rule used to be written once, for a BARE `T` receiver, so
        `dup<T>(p: (T, Int)) { p.copy() }` compiled unbounded and double-freed
        at a move-only argument. The wrapper arms each reasoned locally — the
        tuple arm's own comment says a tuple mentioning a type parameter
        "settles at the instantiation", and nothing ever settled it.

        ONE call, at the top of `_check_copy_call`, covers the whole matrix:
        bare `T`, `(T, Int)`, `T?`, `[T; N]`, `Vector<T>` and every nesting of
        them, because the parameter walk is recursive and the caller gates on
        `copy_tier(...) == 'abstract'` — which is true exactly when the answer
        depends on the type argument. A receiver whose type DECLARES its own
        copy policy (`Vector<T>`, a `Holder<T>: ExplicitCopy` with a
        hand-written body) is not abstract, so it keeps answering for itself.
        """
        env = getattr(self, 'current_type_params', None) or {}
        out: List[str] = []
        for name in self._tier_abstract_params_in(saw_type):
            bounds = [b.rsplit('.', 1)[-1] for b in (env.get(name) or [])]
            if any(b in _COPY_FAMILY_BOUNDS for b in bounds):
                continue
            out.append(name)
        return out

    # ------------------------------------------------------------------
    # Definition side: the coverage rules.
    # ------------------------------------------------------------------

    def _tier_check_declaration(self, decl_node, type_params, what: str,
                                name: str, is_public: bool, line: int,
                                column: int) -> None:
        """The two definition-time rules over an inferred requirement.

        COVERAGE — a DECLARED copy-family bound the body exceeds is an error.
        `<T: ExplicitCopy>` says "duplicable, with ceremony"; a body that
        duplicates `T` with nothing written needs the silent tier, and the gap
        between the two is design 146's sentence exactly: the same line would
        be a copy for some instantiations and an alias for others.

        THE PUBLIC-DECLARATION RULE (design 219 unit C4, ruled HARD-REQUIRE) —
        a module-public generic whose inferred requirement exceeds move-only
        must SPELL its bound. Pure inference means editing a body can tighten a
        published contract with no signature change; an API contract enforced
        only by an off-by-default warning is not a contract. Private and
        internal generics ride inference freely.
        """
        reqs = getattr(decl_node, 'tier_requirements', None) or {}
        for tp in (type_params or []):
            entry = reqs.get(tp.name)
            if entry is None or entry[0] != REQ_COPY:
                continue
            bounds = list(tp.bounds or [])
            if any(b.rsplit('.', 1)[-1] in _SILENT_BOUNDS for b in bounds):
                continue                      # declared, and it covers the body
            _req, reason, rline = entry
            declared_family = [b for b in bounds
                               if b.rsplit('.', 1)[-1] in _COPY_FAMILY_BOUNDS]
            if declared_family:
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"{what} `{name}` declares `<{tp.name}: "
                    f"{declared_family[0]}>`, but its body needs `{tp.name}` to "
                    f"be `Copy`: {reason}",
                    rline or line, column,
                    hint=f"an `ExplicitCopy` bound licenses a SPELLED "
                         f"`.copy()` and nothing else — reading the value out "
                         f"unwritten would be a copy for some instantiations "
                         f"and an alias for others. Write `<{tp.name}: Copy>`, "
                         f"or spell the duplicate `.copy()`",
                    source_file=getattr(decl_node, 'source_file', None) or None,
                )
                continue
            if is_public:
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"public {what} `{name}` must declare the tier it requires: "
                    f"`{tp.name}` has to be `Copy`, because {reason}",
                    rline or line, column,
                    hint=f"write `<{tp.name}: Copy>` in the signature. A public "
                         f"generic's requirement is part of its contract, and "
                         f"an inferred one can tighten when the body is edited "
                         f"— which would break callers with no signature "
                         f"change. Private and internal generics infer it",
                    source_file=getattr(decl_node, 'source_file', None) or None,
                )

    # ------------------------------------------------------------------
    # Call side: record now, discharge at finalize.
    # ------------------------------------------------------------------

    def _tier_record_obligation(self, callee_decl, type_params, type_map,
                                display: str, line: int, column: int) -> None:
        """Record one call site's obligation to satisfy `callee_decl`'s
        requirements. See the module docstring for the entry-point list.

        `callee_decl` is the callee's `Function`/`Method` AST node — the same
        object the definition side stamps, reached through
        `FunctionSymbol.ast_node`, which registration fills for exactly the
        generic declarations this rule quantifies over.
        """
        callee_decl = getattr(callee_decl, 'ast_node', callee_decl)
        if callee_decl is None or not type_params or not type_map:
            return
        env = dict(getattr(self, 'current_type_params', None) or {})
        # The argument is JUDGED HERE, in the caller's namespace, not at
        # finalize: by then `self.namespace` is whatever the last module left
        # behind, and a type declared in this module would answer 'free'.
        args = {}
        for tp in type_params:
            arg = type_map.get(tp.name)
            if arg is None:
                continue
            abstract = self._tier_params_of(arg, env)
            if abstract:
                args[tp.name] = (arg, abstract, True, 'abstract')
            else:
                args[tp.name] = (
                    arg, (), self.namespace.type_satisfies_copy_bound(arg),
                    self.namespace.copy_tier(arg))
        if not args:
            return
        self._tier_obligations.append((
            callee_decl, args, display, line, column, env,
            getattr(self, '_tier_req_decl', None),
            self._tier_current_source_file(),
        ))

    def _tier_check_instance_unsafe(self, callee_sym, display: str,
                                    type_map, line: int, column: int) -> None:
        """Design 130's signature rule, DERIVED per INSTANCE (DF-217k).

        A function whose signature RECEIVES or RETURNS a value of unsafe type is
        declared `unsafe`. The rule ran once, with `T` abstract, so `idn<T>` at
        `T = UnsafePointer<Int8>` received and returned an unsafe value with an
        empty effect slot — while the concrete twin was refused at its
        declaration. The instantiated signature is the one a reader of the call
        site sees, and it was lying about its domain.

        The anchor is the CALL, because that is where the type argument that
        makes the signature unsafe is written; the TEMPLATE is exempt when it
        was already unsafe on its own terms (the declaration check fired there).
        """
        if callee_sym is None or not type_map:
            return
        if getattr(callee_sym, 'is_unsafe', False):
            return
        decl = getattr(callee_sym, 'ast_node', None)
        if decl is not None and self._unsafe_check_exempt(decl):
            return
        signature = list(callee_sym.param_types or []) + [callee_sym.return_type]
        for t in signature:
            if t is None:
                continue
            if self._first_unsafe_type(t) is not None:
                continue           # unsafe before substitution: not ours to say
            found = self._first_unsafe_type(t.substitute(type_map))
            if found is None:
                continue
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"{display} is not declared `unsafe`, but this instantiation's "
                f"signature names a value of unsafe type (`{found}`)",
                line, column,
                hint="declare the generic `unsafe` — calling an unsafe function "
                     "from safe code needs no ceremony, so the marker costs its "
                     "other instantiations nothing and buys every reader a "
                     "signature that tells the truth. Or keep the unsafe type "
                     "out of the type argument"
            )
            return

    def _tier_current_source_file(self) -> Optional[str]:
        for holder in (getattr(self, 'current_method', None),
                       getattr(self, 'current_function', None)):
            src = getattr(holder, 'source_file', None)
            if src:
                return src
        return None

    def _tier_discharge_all(self) -> None:
        """Discharge every recorded obligation, after the whole program is
        checked (so every body has been walked) and to a FIXPOINT (so a
        requirement forwarded through two generic hops reaches the outermost
        caller's argument).
        """
        obligations = getattr(self, '_tier_obligations', None)
        if not obligations:
            return
        # Consumed, so a second finalize (the module path and the whole-program
        # path each call this, and a nested check can reach both) cannot report
        # the same call twice.
        self._tier_obligations = []
        # Propagate first, refuse second: a caller that ACQUIRES a requirement
        # by forwarding must have acquired it before its own callers are judged.
        for _ in range(len(obligations) + 2):
            changed = False
            for ob in obligations:
                changed = self._tier_propagate(ob) or changed
            if not changed:
                break
        for ob in obligations:
            self._tier_refuse(ob)

    def _tier_propagate(self, ob) -> bool:
        """If an argument is the CALLER's own abstract parameter and the
        caller's declared bounds do not already prove the tier, the caller
        inherits the requirement. Returns whether anything changed."""
        callee_decl, args, _display, line, _col, env, caller_decl, _src = ob
        if caller_decl is None:
            return False
        reqs = getattr(callee_decl, 'tier_requirements', None) or {}
        changed = False
        for pname, (_arg, abstract_names, _ok, _tier) in args.items():
            entry = reqs.get(pname)
            if entry is None or entry[0] != REQ_COPY:
                continue
            for abstract in abstract_names:
                if any(b.rsplit('.', 1)[-1] in _SILENT_BOUNDS
                       for b in (env.get(abstract) or [])):
                    continue
                caller_reqs = dict(
                    getattr(caller_decl, 'tier_requirements', None) or {})
                prev = caller_reqs.get(abstract)
                if prev is not None and prev[0] == REQ_COPY:
                    continue
                caller_reqs[abstract] = (
                    REQ_COPY,
                    f"it forwards `{abstract}` to `{_display}`, which needs it "
                    f"to be `Copy`", line)
                caller_decl.tier_requirements = caller_reqs
                changed = True
        return changed

    def _tier_refuse(self, ob) -> None:
        """The refusal: the caller's line, the requirement, the reason, and the
        definition anchor."""
        callee_decl, args, display, line, column, env, _caller, src = ob
        reqs = getattr(callee_decl, 'tier_requirements', None) or {}
        for pname, (arg, abstract_names, satisfies, tier) in args.items():
            entry = reqs.get(pname)
            if entry is None or entry[0] != REQ_COPY:
                continue
            if abstract_names:
                continue                     # abstract: handled by propagation
            if satisfies:
                continue
            _req, reason, rline = entry
            says = ("move-only" if tier == 'nocopy'
                    else "duplicated only by a spelled `.copy()`"
                    if tier == 'explicit' else "not on the `Copy` tier")
            self._error(
                ErrorKind.CANNOT_COPY,
                f"{display} requires `{pname}` to be `Copy` — {reason}; "
                f"`{arg}` is {says}",
                line, column,
                hint=f"pass a type on the `Copy` tier, or rewrite the body to "
                     f"move `{pname}` instead of duplicating it. A body that "
                     f"means to duplicate declares `<{pname}: ExplicitCopy>` "
                     f"and spells `.copy()`",
                source_file=src,
            )

    def _tier_params_of(self, arg: Optional[SawType], env: Dict) -> List[str]:
        """The abstract parameter names of `env` that `arg` names."""
        if arg is None:
            return []
        out: List[str] = []

        def visit(t, d):
            if t is None or d > 12:
                return
            if t.kind == TypeKind.STRUCT and t.struct_name in env:
                if t.struct_name not in out:
                    out.append(t.struct_name)
                return
            for sub in (t.type_args or []):
                visit(sub, d + 1)
            visit(getattr(t, 'inner_type', None), d + 1)
            visit(getattr(t, 'array_element_type', None), d + 1)
            for sub in (getattr(t, 'element_types', None) or []):
                visit(sub, d + 1)

        visit(arg, 0)
        return out
