#!/usr/bin/env python3
"""The type evidence for the corpus migration: sawc's front end, observed.

    python instrument.py OUT.json -- <sawc arguments...>

Runs `sawc.main()` in-process on one entry and records every window the
place-lowering pass synthesizes (`place_uses._PlaceUses._window_call`, with the
caller that produced it), every closure argument that receives a reference,
and every declaration the pass walks. The compile stops right after the first
place-lowering pass, so nothing is generated. Each record carries the source
anchors the rewriter needs, read from the typed AST before the pass rewrites
it; the rewriter never parses a type out of text (SL:borrow-survey,
Methodology).

The pass does not walk trait default bodies, static initializers, default
parameter values or synthesized declarations, and a file that fails before
lowering is not walked at all; `walked` records exactly what was seen, so the
parser-only scan can flag the rest.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "sawc"))

import dataclasses  # noqa: E402

import place_uses as PU  # noqa: E402
from ast_nodes import (  # noqa: E402
    ArrayIndex, AssignStatement, BindOptional, BreakStatement, ClosureExpr,
    CompoundAssignStatement, ContinueStatement, ForceUnwrap, FunctionCall,
    Identifier, MemberAccess, MethodCall, MoveExpr, OptionalEvalExpr,
    ReferenceExpr, ReturnStatement, SelfExpr, TryExpr, TupleIndex, TypeKind,
    Argument,
)
from ast_walk import child_nodes  # noqa: E402


class StopFront(BaseException):
    """Raised after the first place-lowering pass: nothing past it matters."""


RECORDS = []
STATE = {"pass": 0, "parents": {}}


def emit(kind, **fields):
    fields["kind"] = kind
    RECORDS.append(fields)


def rel(path):
    if not path:
        return path
    path = os.path.realpath(path)
    root = os.path.realpath(REPO) + os.sep
    return path[len(root):] if path.startswith(root) else path


def tstr(t):
    try:
        return str(t) if t is not None else None
    except Exception:  # noqa: BLE001 - a type that cannot render is still evidence of absence
        return "<?>"


def pos(node):
    return [getattr(node, "line", 0) or 0, getattr(node, "column", 0) or 0]


def step_down(node):
    """One step toward the root of a postfix chain, or None at its root."""
    if isinstance(node, (MemberAccess, MethodCall)):
        if isinstance(node, MethodCall) and getattr(node, "is_static_method_call", False):
            return None
        return node.object
    if isinstance(node, ArrayIndex):
        return node.array_expr
    if isinstance(node, TupleIndex):
        return node.tuple_expr
    if isinstance(node, (ForceUnwrap, BindOptional, OptionalEvalExpr)):
        return node.expr
    if isinstance(node, MoveExpr) and node.path is not None:
        return node.path
    return None


def leftmost(node):
    """[line, column, class] of the node a postfix chain starts at."""
    while True:
        nxt = step_down(node)
        if nxt is None:
            return pos(node) + [type(node).__name__]
        node = nxt


def chain_desc(top, place):
    out = []
    node = top
    while node is not None and node is not place:
        if isinstance(node, MethodCall):
            out.append("call:" + node.method_name)
        elif isinstance(node, MemberAccess):
            out.append("field:" + node.member)
        elif isinstance(node, ArrayIndex):
            out.append("index")
        elif isinstance(node, TupleIndex):
            out.append("tuple:" + str(node.index))
        elif isinstance(node, ForceUnwrap):
            out.append("!")
        elif isinstance(node, BindOptional):
            out.append("?")
        elif isinstance(node, OptionalEvalExpr):
            out.append("?eval")
        else:
            out.append(type(node).__name__)
            break
        node = step_down(node)
    return out


def names_in(node, acc=None, into_closures=True):
    acc = set() if acc is None else acc
    if isinstance(node, Identifier):
        acc.add(node.name)
    elif isinstance(node, SelfExpr):
        acc.add("self")
    for child in child_nodes(node):
        if not into_closures and isinstance(child, ClosureExpr):
            continue
        names_in(child, acc, into_closures)
    return acc


def exits_in(body):
    """The control transfers in a closure body that a block would retarget."""
    found = set()
    stack = [body]
    while stack:
        node = stack.pop()
        if isinstance(node, ClosureExpr) and node is not body:
            continue
        if isinstance(node, ReturnStatement):
            found.add("return")
        elif isinstance(node, BreakStatement):
            found.add("break")
        elif isinstance(node, ContinueStatement):
            found.add("continue")
        elif isinstance(node, TryExpr) and getattr(node, "variant", None) == "propagate":
            found.add("try")
        stack.extend(child_nodes(node))
    return sorted(found)


def field_of(parent, child):
    """The field of `parent` that holds `child`, as `name` or `name[i]`."""
    for f in dataclasses.fields(parent):
        value = getattr(parent, f.name, None)
        if value is child:
            return f.name
        if isinstance(value, Argument) and value.value is child:
            return f.name
        if isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if item is child or (isinstance(item, Argument) and item.value is child):
                    return "%s[%d]" % (f.name, i)
                if isinstance(item, tuple) and any(x is child for x in item):
                    return "%s[%d]" % (f.name, i)
    return "?"


def index_parents(node, parent=None):
    stack = [(node, parent)]
    parents = STATE["parents"]
    while stack:
        n, p = stack.pop()
        if p is not None:
            parents[id(n)] = (p, n)
        for c in child_nodes(n):
            stack.append((c, n))


def context(node, depth=3):
    """The chain of parents above `node`: [{type, field, pos}, ...]."""
    out = []
    parents = STATE["parents"]
    cur = node
    for _ in range(depth):
        entry = parents.get(id(cur))
        if entry is None or entry[1] is not cur:
            break
        parent = entry[0]
        item = {"type": type(parent).__name__, "field": field_of(parent, cur), "pos": pos(parent)}
        for attr in ("name", "mutable", "op"):
            value = getattr(parent, attr, None)
            if isinstance(value, (str, bool)):
                item[attr] = value
        if getattr(parent, "pattern", None) is not None:
            item["pattern"] = type(parent.pattern).__name__
        out.append(item)
        cur = parent
    return out


def value_summary(value):
    if value is None:
        return None
    return {"type": type(value).__name__, "pos": pos(value), "left": leftmost(value),
            "names": sorted(names_in(value)),
            "resolved": tstr(getattr(value, "resolved_type", None))}


# ---------------------------------------------------------------- the window hook
_orig_window_call = PU._PlaceUses._window_call
_orig_decl = PU._PlaceUses._decl
_orig_replace_head = PU._PlaceUses._replace_head


def _replace_head(self, expr, place, name, head_type=None):
    # The pass rewrites a chain's head before it opens the window, so the
    # chain is read here, from its outermost (first) call.
    STATE.setdefault("chains", {}).setdefault(id(place), (place, chain_desc(expr, place)))
    return _orig_replace_head(self, expr, place, name, head_type)


def snapshot_chain(place, fallback):
    entry = STATE.get("chains", {}).get(id(place))
    return entry[1] if entry is not None and entry[0] is place else fallback


def _window_call(self, place, param_name, body, result_type, exclusive, absent):
    if STATE["pass"] != 1:
        return _orig_window_call(self, place, param_name, body, result_type, exclusive, absent)
    frame = sys._getframe(1)
    caller = frame.f_code.co_name
    loc = frame.f_locals
    grand = sys._getframe(2).f_code.co_name
    info = {"caller": caller, "grand": grand}
    if caller == "_chain_window":
        expr = loc.get("expr")
        unwrap_read = bool(loc.get("unwrap_read"))
        bare = (expr is place) or unwrap_read
        info.update(bare=bare, unwrap_read=unwrap_read,
                    chain=snapshot_chain(place, []) if not bare else chain_desc(expr, place),
                    nested_outer=grand == "_window_call",
                    expr_pos=pos(expr), expr_type=type(expr).__name__, ctx=context(expr),
                    expr_resolved=tstr(getattr(expr, "resolved_type", None)))
    elif caller == "_assignment":
        stmt = loc.get("stmt")
        chain = snapshot_chain(place, [])
        info.update(stmt_type=type(stmt).__name__, stmt_pos=pos(stmt),
                    compound=getattr(stmt, "op", None) if isinstance(stmt, CompoundAssignStatement) else None,
                    whole=chain == [], force_whole=chain == ["!"], chain=chain,
                    hoisted=loc.get("hoist") is not None, value=value_summary(stmt.value),
                    ctx=context(stmt))
    elif caller == "_span_call":
        ref = loc.get("ref")
        call = loc.get("expr")
        info.update(ref_pos=pos(ref), ref_mutable=bool(getattr(ref, "mutable", False)),
                    chain=snapshot_chain(place, []),
                    n_refs=len(loc.get("refs") or []),
                    callee=getattr(call, "method_name", None) or getattr(call, "name", None),
                    forwarded_lend=getattr(call, "name", None) == "__window",
                    call_pos=pos(call), ctx=context(ref))
    elif caller == "_chain_assign_window":
        node = loc.get("node")
        info.update(want=loc.get("want"), compound=getattr(node, "op", None),
                    node_pos=pos(node), chain=chain_desc(getattr(node.target, "expr", node.target), place),
                    value=value_summary(node.value), ctx=context(node))
    elif caller == "_borrow_match":
        match = loc.get("expr")
        arms = []
        for arm in match.arms:
            arms.append({"pos": pos(arm), "variant": getattr(arm, "variant_name", None),
                         "bindings": [str(b) for b in (getattr(arm, "bindings", None) or [])],
                         "lent": [str(b) for b in (getattr(arm, "lent_bindings", None) or [])],
                         "pattern": type(arm.pattern).__name__ if getattr(arm, "pattern", None) is not None else None})
        info.update(match_pos=pos(match), arms=arms, ctx=context(match))
    elif caller == "_presence_condition":
        info.update(ctx=context(place))
    elif caller == "_borrow_operand_window":
        info.update(ctx=context(place))
    recv = self._place_receiver(place)
    elem = getattr(place, "place_elem_type", None)
    struct = getattr(place, "place_struct", None)
    accessor = self._accessor_node(struct, getattr(place, "place_method", None))
    emit("window", file=rel(self._file), line=pos(place)[0], col=pos(place)[1],
         accessor_file=rel(getattr(accessor, "source_file", None)),
         struct=getattr(place, "place_struct", None), method=getattr(place, "place_method", None),
         optional=bool(getattr(place, "place_optional", False)),
         subscript=isinstance(place, ArrayIndex),
         key=(value_summary(place.index) if isinstance(place, ArrayIndex)
              and getattr(place, "index", None) is not None else None),
         args=([value_summary(a.value if isinstance(a, Argument) else a)
                for a in (getattr(place, "arguments", None) or [])]
               if isinstance(place, MethodCall) else None),
         elem=tstr(elem), elem_kind=(elem.kind.name if elem is not None else None),
         tier=self.ns.copy_tier(elem) if elem is not None else None,
         policy=self.ns.read_policy(elem) if elem is not None else None,
         exclusive=bool(exclusive), absent=absent,
         root=self._access_root(recv), recv_left=leftmost(recv),
         recv_type=tstr(getattr(recv, "resolved_type", None)),
         # Any `&self` body, a `borrows` one included: sawc's own design-200
         # state covers plain `&self` bodies only.
         shared_self_body=STATE.get("self_mode") == "ref",
         self_cell=STATE.get("self_cell", False),
         accessor_self=receiver_mode(accessor),
         exclusive_only=self._exclusive_only(getattr(place, "place_struct", None),
                                             getattr(place, "place_method", None)),
         decl=STATE.get("decl"), synthesized=STATE.get("synthesized", False), **info)
    return _orig_window_call(self, place, param_name, body, result_type, exclusive, absent)


def receiver_mode(decl):
    """`var`, `ref` or `value` for a method's receiver; None for a function,
    a static method or an initializer."""
    if decl is None or getattr(decl, "is_static", False) or getattr(decl, "is_init", False):
        return None
    if getattr(decl, "self_mutable", False):
        return "var"
    if getattr(decl, "self_is_reference", False):
        return "ref"
    return "value" if hasattr(decl, "self_is_reference") else None


def _decl(self, decl, ext=None):
    if STATE["pass"] == 1 and getattr(decl, "body", None) is not None:
        STATE["decl"] = getattr(decl, "name", None)
        STATE["self_mode"] = receiver_mode(decl) if ext is not None else None
        owner = getattr(ext, "struct_name", None) if ext is not None else None
        STATE["self_cell"] = bool(owner) and self.ns.struct_is_cell_carrying(owner)
        # A derived conformance's body is generated at the attribute, so it
        # has no source of its own either.
        STATE["synthesized"] = bool(
            getattr(decl, "is_mono_instance", False) or getattr(decl, "is_synthesized", False)
            or any(getattr(decl, f, False) for f in (
                "is_derived_copy", "is_derived_equals", "is_derived_compare", "is_derived_hash",
                "is_derived_serialize", "is_derived_deserialize")))
        if not STATE["synthesized"]:
            emit("walked", file=rel(getattr(decl, "source_file", None)), line=pos(decl)[0],
                 col=pos(decl)[1], name=getattr(decl, "name", None),
                 ext=getattr(ext, "struct_name", None) if ext is not None else None)
    return _orig_decl(self, decl, ext)


PU._PlaceUses._window_call = _window_call
PU._PlaceUses._decl = _decl
PU._PlaceUses._replace_head = _replace_head

_orig_transform = PU.transform_place_uses


def _transform(programs, namespace, reporter, uncheck_after=True):
    STATE["pass"] += 1
    if STATE["pass"] == 1:
        for program in programs:
            index_parents(program)
        census(programs, namespace)
    result = _orig_transform(programs, namespace, reporter, uncheck_after)
    if STATE["pass"] == 1:
        emit("lowered", errors=bool(reporter.has_errors()))
        raise StopFront()
    return result


PU.transform_place_uses = _transform


# ---------------------------------------------------------------- closure census
def owner_name(t):
    if t is None:
        return None
    if t.kind == TypeKind.STRUCT:
        return t.struct_name
    if t.kind == TypeKind.ENUM:
        return t.enum_name
    if t.kind == TypeKind.REFERENCE and t.inner_type is not None:
        return owner_name(t.inner_type)
    return tstr(t)


def decls(program):
    for fn in getattr(program, "functions", None) or []:
        yield fn
    for ext in getattr(program, "extensions", None) or []:
        for m in getattr(ext, "methods", None) or []:
            yield m
    for md in getattr(program, "module_decls", None) or []:
        if getattr(md, "body", None) is not None:
            yield from decls(md.body)


def census(programs, ns):
    for program in programs:
        for decl in decls(program):
            if getattr(decl, "is_mono_instance", False) or getattr(decl, "is_synthesized", False):
                continue
            src = rel(getattr(decl, "source_file", None))
            bound = bindings_in(decl)
            stack = [getattr(decl, "body", None)]
            while stack:
                node = stack.pop()
                if node is None:
                    continue
                if isinstance(node, (MethodCall, FunctionCall)):
                    closure_call(node, src, ns, getattr(decl, "name", None), bound)
                stack.extend(child_nodes(node))


def bindings_in(decl):
    """{name: count} of every binding the declaration introduces, anywhere in
    it: parameters, `let`s, loop and `if let` names and patterns. A superset
    of what is in scope at any one point. Closure parameters are left out:
    two sibling closures' blocks do not shadow each other."""
    from ast_nodes import ForLoop, GuardLetStatement, IfLetExpr, LetStatement, MatchArm
    from ast_walk import pattern_binding_names
    names = {}

    def add(name):
        if isinstance(name, str) and name and name != "_":
            names[name] = names.get(name, 0) + 1

    for p in getattr(decl, "parameters", None) or []:
        add(p.name)
    stack = [getattr(decl, "body", None)]
    while stack:
        n = stack.pop()
        if n is None:
            continue
        if isinstance(n, (LetStatement, IfLetExpr, GuardLetStatement)):
            add(n.name)
        if isinstance(n, ForLoop):
            add(getattr(n, "variable", None))
        pattern = getattr(n, "pattern", None)
        if pattern is not None and not isinstance(pattern, str):
            for name in pattern_binding_names(pattern):
                add(name)
        if isinstance(n, MatchArm):
            for b in getattr(n, "bindings", None) or []:
                add(b if isinstance(b, str) else getattr(b, "name", None))
        stack.extend(child_nodes(n))
    return names


def closure_call(call, src, ns, dname, bound):
    args = list(call.arguments or [])
    for idx, arg in enumerate(args):
        value = arg.value if isinstance(arg, Argument) else arg
        if not isinstance(value, ClosureExpr):
            continue
        ctype = getattr(value, "resolved_type", None)
        ptypes = list(getattr(ctype, "param_types", None) or []) if ctype is not None else []
        ref_params = [tstr(t) for t in ptypes if t is not None and t.kind == TypeKind.REFERENCE]
        ref_caps = [c.name + ":" + c.mode for c in (value.capture_specs or [])
                    if c.mode in ("ref", "ref_var")]
        explicit = [p.name for p in value.parameters if p.is_reference]
        if not ref_params and not getattr(value, "has_reference_params", False) \
                and not explicit and not ref_caps:
            continue
        owner = None
        if isinstance(call, MethodCall):
            if getattr(call, "is_static_method_call", False):
                owner = call.static_receiver
            else:
                owner = owner_name(getattr(call.object, "resolved_type", None))
        root = None
        if isinstance(call, MethodCall) and not getattr(call, "is_static_method_call", False):
            node = call.object
            while node is not None:
                if isinstance(node, Identifier):
                    root = node.name
                    break
                if isinstance(node, SelfExpr):
                    root = "self"
                    break
                node = step_down(node)
        body_names = names_in(value.body)
        callee_file = None
        if owner is not None and isinstance(call, MethodCall):
            info = ns.lookup_method(owner.split("<")[0], call.method_name)
            callee_file = rel(getattr(getattr(info, "ast_node", None), "source_file", None))
        emit("closure", file=src, line=pos(call)[0], col=pos(call)[1], func=dname,
             callee_file=callee_file,
             owner=owner, owner_type=tstr(getattr(getattr(call, "object", None), "resolved_type", None)),
             callee=getattr(call, "method_name", None) or getattr(call, "name", None),
             call_type=type(call).__name__, arg_index=idx, n_args=len(args),
             args=[value_summary(a.value if isinstance(a, Argument) else a) for a in args],
             arg_labels=[getattr(a, "name", None) if isinstance(a, Argument) else None for a in args],
             recv_left=(leftmost(call.object) if isinstance(call, MethodCall) else None),
             closure_pos=pos(value), body_pos=pos(value.body),
             params=[{"name": p.name, "pos": [p.line or 0, p.column or 0],
                      "typed": p.type_annotation is not None, "ref": p.is_reference}
                     for p in value.parameters],
             shorthand=getattr(value, "shorthand_param_count", 0) or 0,
             capture_specs=[{"name": c.name, "mode": c.mode} for c in (value.capture_specs or [])],
             ref_params=ref_params, closure_type=tstr(ctype), root=root,
             captures_root=root is not None and (root in body_names
                                                 or root in (getattr(value, "captures", None) or [])),
             exits=exits_in(value.body), body_names=sorted(body_names),
             # A parameter name bound elsewhere in the declaration too: as a
             # block's binding it could shadow an enclosing one.
             shadow_risk=sorted(p.name for p in value.parameters if p.name in bound),
             result_type=tstr(getattr(call, "resolved_type", None)), ctx=context(call))


# ---------------------------------------------------------------- run
def main():
    out = sys.argv[1]
    assert sys.argv[2] == "--", "usage: instrument.py OUT.json -- <sawc arguments...>"
    import sawc as sawc_main
    sys.argv = ["sawc.py"] + sys.argv[3:]
    status = "completed-without-lowering"
    try:
        sawc_main.main()
    except StopFront:
        status = "stopped-after-places"
    except SystemExit as e:
        status = "exit:%s" % (e.code,)
    except Exception as e:  # noqa: BLE001 - a crash is a status, recorded, never hidden
        import traceback
        status = "exception:" + type(e).__name__
        emit("traceback", text=traceback.format_exc())
    emit("status", status=status)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(RECORDS, fh, default=str, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
