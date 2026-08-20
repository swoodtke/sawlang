"""Documentation extraction — the `--emit-docs` JSON (design 121).

Reads the TYPE-CHECKED program: declarations come from the ASTs, and everything
a reader cannot see in the source text — resolved types, trait conformances,
whether a function suspends — comes from the namespaces and the effect graph the
typechecker built. The result is the input format for the `sawdoc` site
generator; the compiler's job ends at the JSON.

Shape (schema_version 3):

    {"schema_version": 3,
     "modules": [
       {"name": "std.time", "source": "time.saw", "doc": "...",
        "items": [ ... ]}]}

An item always carries `kind`, `name`, `signature`, `visibility`, `doc`, `line`.
Kind-specific keys follow: `generics`/`conformances` on types, `fields` on a
struct, `cases` on an enum, `methods` on a trait or extension, and
`params`/`returns`/`effect`/`self`/`static` on anything callable.

Design 144: a type's identity is `(defining module, name)`, so an item that
NAMES a type — struct, enum, trait, typealias, extension — also carries
`module`, the dotted path of the module that defines it. Names and rendered
types stay SHORT everywhere (the internal qualified spelling never appears in
this JSON); `module` is what tells two packages' `Header`s apart.

Ordering is total and machine-independent (modules by name, items by kind then
name then line, members in declaration order), and `source` is a basename, so the
JSON diffs cleanly and works as a golden.

Visibility filter: members follow the design-80 gate — a private field, method or
init is left out unless `--emit-docs-all` asks for it. Top-level declarations are
not gated by the compiler, so they are all listed with their declared visibility.
"""

import json
import os
from typing import Any, Dict, List, Optional

from ast_nodes import (
    BoolLiteral, EnumInit, FloatLiteral, Identifier, IntLiteral, NoneLiteral,
    StringLiteral, Visibility,
)
from type_identity import decl_identity, display_name

# Item kinds that NAME a type, hence carry a design-144 module qualifier.
_TYPE_ITEM_KINDS = ("struct", "enum", "trait", "typealias", "extension")

# 2 (design 144): every type-naming item gained a `module` field, and names are
# guaranteed SHORT. A type's identity is `(defining module, name)` now, so an
# item's `name` alone no longer distinguishes two packages' `Header`s — the
# consumer needs the pair. The `name` field itself is unchanged in meaning:
# still what the author wrote, never the internal qualified spelling.
#
# 3 (design 236): every callable item gained a `static` field, and a static
# method's `signature` spells the keyword. `"self": null` used to be the only
# way to read staticness off this JSON, which mirrored the language's own
# inference; both are declarations now.
SCHEMA_VERSION = 3

# Compiler-synthesized declarations (coroutine frames, drive/spawn wrappers) are
# never part of a documented surface.
_SYNTHETIC_PREFIXES = ("__", "_CatchError_")


def _is_synthetic(name: Optional[str]) -> bool:
    return bool(name) and name.startswith(_SYNTHETIC_PREFIXES)


def _visibility_str(vis) -> str:
    if vis == Visibility.PUBLIC:
        return "public"
    if vis == Visibility.PACKAGE:
        return "public(package)"
    if vis == Visibility.PARENT:
        return "public(parent)"
    return "private"


def _vis_prefix(vis) -> str:
    s = _visibility_str(vis)
    return "" if s == "private" else s + " "


def _type_str(t) -> Optional[str]:
    """Render a resolved `SawType` in Saw syntax (`SawType.__repr__` is that
    rendering; it is what diagnostics print)."""
    return None if t is None else str(t)


def _conformance_suffix(traits) -> str:
    """The `: Trait, Other` tail of a declaration, empty when there are none."""
    return ": " + ", ".join(traits) if traits else ""


def _expr_str(expr) -> str:
    """Render a default-value expression. Defaults are constant-ish by nature, so
    the literal forms cover them; anything else names its node kind."""
    if isinstance(expr, (IntLiteral, FloatLiteral)):
        return str(expr.value)
    if isinstance(expr, BoolLiteral):
        return "true" if expr.value else "false"
    if isinstance(expr, StringLiteral):
        return '"%s"' % expr.value
    if isinstance(expr, Identifier):
        return expr.name
    if isinstance(expr, NoneLiteral):
        return "None"
    if isinstance(expr, EnumInit):
        return "%s.%s" % (expr.enum_name, expr.variant_name)
    return "<%s>" % type(expr).__name__


def _generics(type_params) -> List[Dict[str, Any]]:
    out = []
    for tp in type_params or []:
        entry = {
            "name": tp.name,
            "bounds": list(tp.bounds or []),
            "default": _type_str(tp.default),
        }
        # A const VALUE parameter (design 148) carries a value type instead of
        # bounds; readers key on `const` rather than on an empty bounds list.
        if getattr(tp, 'is_const', False):
            entry["const"] = True
            entry["value_type"] = _type_str(tp.const_type)
        out.append(entry)
    return out


def _generics_str(type_params) -> str:
    if not type_params:
        return ""
    parts = []
    for tp in type_params:
        if getattr(tp, 'is_const', False):
            s = "const %s: %s" % (tp.name, _type_str(tp.const_type))
        else:
            s = tp.name
            if tp.bounds:
                s += ": " + " + ".join(tp.bounds)
        if tp.default is not None:
            s += " = " + _type_str(tp.default)
        parts.append(s)
    return "<" + ", ".join(parts) + ">"


class DocsBuilder:
    """Builds the documentation tree for one compilation."""

    def __init__(self, ctx: Dict[str, Any], include_private: bool = False):
        self.entry_ast = ctx["entry_ast"]
        self.entry_path = ctx["entry_path"]
        self.module_map = ctx["module_map"]
        self.builtin_ast = ctx["builtin_ast"]
        self.namespace = ctx["namespace"]
        self.typechecker = ctx["typechecker"]
        self.include_private = include_private
        builtin_ns = ctx["builtin_ns"]
        # std bodies are checked (and their effect fixpoint run) by the separate
        # builtin typechecker — design 84 — so their suspend facts arrive as
        # these two sets rather than in this compilation's effect graph. They are
        # the FALLBACK in `_effect`; the program's own graph always wins.
        self._std_suspending_methods = getattr(
            builtin_ns, "_std_suspending_methods", set()) or set()
        self._std_suspending_functions = getattr(
            builtin_ns, "_std_suspending_functions", set()) or set()
        self._file_module_docs = getattr(
            self.builtin_ast, "file_module_docs", {}) or {}

    # ------------------------------------------------------------------ modules
    def build(self) -> Dict[str, Any]:
        modules = []
        seen = set()

        def add(name, source, doc, decls):
            if name in seen:
                return
            seen.add(name)
            items = self._items(decls, name)
            modules.append({"name": name, "source": os.path.basename(source or ""),
                            "doc": doc, "items": items})

        entry_name = os.path.splitext(os.path.basename(self.entry_path))[0]
        add(entry_name, self.entry_path, self.entry_ast.module_doc,
            self._decls_of(self.entry_ast))

        for path, ast in self.module_map.items():
            src = self._first_source_file(ast) or ""
            add(".".join(path), src, ast.module_doc, self._decls_of(ast))

        for leaf in self._imported_std_leaves():
            decls = [d for d in self._decls_of(self.builtin_ast)
                     if self._leaf_of(d) == leaf]
            if not decls:
                continue
            path = self._std_path(leaf)
            add("std." + leaf, path, self._file_module_docs.get(path), decls)

        modules.sort(key=lambda m: m["name"])
        return {"schema_version": SCHEMA_VERSION, "modules": modules}

    def _std_path(self, leaf: str) -> str:
        from type_identity import std_leaf
        for p in self._file_module_docs:
            if std_leaf(p) == leaf:
                return p
        return leaf.replace(".", os.sep) + ".saw"

    def _imported_std_leaves(self) -> List[str]:
        """The std modules this compilation asked for by name. A doc driver is
        just a file that imports the modules it wants documented."""
        leaves = []
        asts = [self.entry_ast] + list(self.module_map.values())
        for ast in asts:
            for imp in getattr(ast, "imports", []) or []:
                path = list(imp.path or [])
                if path and path[-1] == "*":
                    path = path[:-1]
                if len(path) < 2 or path[0] != "std":
                    continue
                leaf = ".".join(path[1:])
                if leaf not in leaves:
                    leaves.append(leaf)
        leaves.sort()
        return leaves

    @staticmethod
    def _leaf_of(decl) -> Optional[str]:
        from type_identity import std_leaf
        return std_leaf(getattr(decl, "source_file", None))

    @staticmethod
    def _first_source_file(ast) -> Optional[str]:
        for group in ("structs", "functions", "enums", "traits", "extensions",
                      "statics"):
            for d in getattr(ast, group, []) or []:
                src = getattr(d, "source_file", None)
                if src:
                    return src
        return None

    @staticmethod
    def _decls_of(ast) -> List[Any]:
        decls = []
        for group in ("structs", "enums", "traits", "extensions",
                      "type_definitions", "statics", "functions"):
            decls.extend(getattr(ast, group, []) or [])
        return decls

    # -------------------------------------------------------------------- items
    def _items(self, decls, module_name: str = "") -> List[Dict[str, Any]]:
        from ast_nodes import (Enum as SawEnum, Extension, Function, StaticDecl,
                               Struct, Trait, TypeDefinition)
        items = []
        for d in decls:
            if _is_synthetic(getattr(d, "name", None)):
                continue
            if isinstance(d, Struct):
                items.append(self._struct_item(d))
            elif isinstance(d, SawEnum):
                items.append(self._enum_item(d))
            elif isinstance(d, Trait):
                items.append(self._trait_item(d))
            elif isinstance(d, Extension):
                if _is_synthetic(d.struct_name):
                    continue
                items.append(self._extension_item(d))
            elif isinstance(d, TypeDefinition):
                items.append(self._alias_item(d))
            elif isinstance(d, StaticDecl):
                items.append(self._static_item(d))
            elif isinstance(d, Function):
                if getattr(d, "is_synthesized", False):
                    continue
                items.append(self._function_item(d))
        # Design 144: a type-naming item carries the module half of its identity.
        for item in items:
            if item["kind"] in _TYPE_ITEM_KINDS:
                item["module"] = module_name
        items.sort(key=lambda i: (i["kind"], i["name"], i["line"]))
        return items

    def _conformances(self, type_identity: str) -> List[str]:
        """Trait names a type conforms to, rendered SHORT (design 144).

        Keyed by the type's IDENTITY — that is what the conformance table
        holds — while the trait names come back out as the author wrote them."""
        traits = (self.namespace.conformances.get(type_identity, {})
                  if self.namespace else {})
        return sorted(display_name(t) for t in traits if not _is_synthetic(t))

    def _struct_item(self, s) -> Dict[str, Any]:
        gen = _generics_str(s.type_params)
        fields = []
        for f in s.fields:
            if f.visibility == Visibility.PRIVATE and not self.include_private:
                continue
            fields.append({"name": f.name, "type": _type_str(f.type),
                           "visibility": _visibility_str(f.visibility),
                           "doc": f.doc, "line": f.line})
        # design 130: an `unsafe struct` is a different type from a plain one
        # that merely happens to be NAMED `Unsafe*`, so the signature has to say
        # which it is — the name alone does not carry the semantics.
        unsafe = "unsafe " if getattr(s, 'is_unsafe', False) else ""
        return {
            "kind": "struct", "name": s.name,
            "signature": "%s%sstruct %s%s" % (_vis_prefix(s.visibility), unsafe,
                                              s.name, gen),
            "visibility": _visibility_str(s.visibility),
            "unsafe": bool(getattr(s, 'is_unsafe', False)),
            "generics": _generics(s.type_params),
            "conformances": self._conformances(decl_identity(s)),
            "fields": fields, "doc": s.doc, "line": s.line,
        }

    def _enum_item(self, e) -> Dict[str, Any]:
        gen = _generics_str(e.type_params)
        cases = []
        for v in e.variants:
            payload = [{"name": n, "type": _type_str(t)}
                       for n, t in (v.associated_types or [])]
            cases.append({"name": v.name, "payload": payload, "doc": v.doc})
        return {
            "kind": "enum", "name": e.name,
            "signature": "%senum %s%s" % (_vis_prefix(e.visibility), e.name, gen),
            "visibility": _visibility_str(e.visibility),
            "generics": _generics(e.type_params),
            "conformances": self._conformances(decl_identity(e)),
            "cases": cases, "doc": e.doc, "line": e.line,
        }

    def _trait_item(self, t) -> Dict[str, Any]:
        gen = _generics_str(t.type_params)
        # Parent traits are type REFERENCES, so they carry identities; the page
        # shows the short names (design 144).
        parent_names = [display_name(p) for p in (t.parent_traits or [])]
        parents = _conformance_suffix(parent_names)
        # A trait method has no visibility of its own — the trait's requirement is
        # as visible as the trait.
        methods = [self._callable(m, owner=t.name, is_trait_method=True,
                                  visibility=t.visibility)
                   for m in t.methods]
        methods.sort(key=lambda m: (m["name"], m["line"]))
        return {
            "kind": "trait", "name": t.name,
            "signature": "%strait %s%s%s" % (_vis_prefix(t.visibility), t.name,
                                             gen, parents),
            "visibility": _visibility_str(t.visibility),
            "generics": _generics(t.type_params),
            "parent_traits": parent_names,
            "methods": methods, "doc": t.doc, "line": t.line,
        }

    def _extension_item(self, x) -> Dict[str, Any]:
        gen = _generics_str(x.type_params)
        # `Extension.struct_name` and the conformance list are type REFERENCES,
        # so they hold identities; the page shows short names (design 144).
        target = display_name(x.struct_name)
        conf_names = [display_name(c) for c in (x.conformances or [])]
        conf = _conformance_suffix(conf_names)
        methods = []
        for m in x.methods:
            if getattr(m, "is_synthesized", False) or _is_synthetic(m.name):
                continue
            if m.visibility == Visibility.PRIVATE and not self.include_private:
                continue
            methods.append(self._callable(m, owner=x.struct_name))
        methods.sort(key=lambda m: (m["name"], m["line"]))
        return {
            "kind": "extension", "name": target,
            "signature": "%sextension %s%s%s" % (_vis_prefix(x.visibility),
                                                 target, gen, conf),
            "visibility": _visibility_str(x.visibility),
            "generics": _generics(x.type_params),
            "conformances": conf_names,
            "methods": methods, "doc": x.doc, "line": x.line,
        }

    def _alias_item(self, a) -> Dict[str, Any]:
        target = _type_str(a.defined_type)
        return {
            "kind": "typealias", "name": a.name,
            "signature": "%stype %s = %s" % (_vis_prefix(a.visibility), a.name, target),
            "visibility": _visibility_str(a.visibility),
            "target": target, "doc": a.doc, "line": a.line,
        }

    def _static_item(self, s) -> Dict[str, Any]:
        ty = _type_str(s.type)
        # design 149: an `unsafe static var` is a different declaration from an
        # immutable static — it is writable, and naming it makes the reader's
        # own function `unsafe`. Both facts belong in the documented signature.
        # The two halves are set together, so one flag renders both words.
        head = "unsafe static var" if getattr(s, 'is_var', False) else "static"
        return {
            "kind": "static", "name": s.name,
            "signature": "%s%s %s: %s" % (_vis_prefix(s.visibility), head,
                                          s.name, ty),
            "visibility": _visibility_str(s.visibility),
            "unsafe": bool(getattr(s, 'is_var', False)),
            "mutable": bool(getattr(s, 'is_var', False)),
            "type": ty, "doc": s.doc, "line": s.line,
        }

    def _function_item(self, f) -> Dict[str, Any]:
        item = self._callable(f, owner=None)
        item["kind"] = "func"
        return item

    # ---------------------------------------------------------------- callables
    def _callable(self, node, owner: Optional[str], is_trait_method: bool = False,
                  visibility=None) -> Dict[str, Any]:
        """One func / method / init entry, including the two things the signature
        alone does not say: whether it suspends, and what it does with `self`."""
        if visibility is None:
            visibility = getattr(node, "visibility", Visibility.PRIVATE)
        params = list(node.parameters or [])
        # design 141: a `borrows` accessor reaches here already LOWERED into its
        # window-closure form, because the place transform runs in `parse_source`
        # so that everything downstream sees an ordinary generic method. Docs
        # document what the AUTHOR wrote (design 121), so undo the rewrite for
        # rendering: drop the synthesized `__window`/`__absent` parameters and
        # the `__R` result type param, and put back the declared place type.
        is_borrows = getattr(node, "is_borrows", False)
        type_params = list(getattr(node, "type_params", None) or [])
        if is_borrows:
            from place_transform import (ABSENT_PARAM, RESULT_TYPE_PARAM,
                                         WINDOW_PARAM)
            params = [p for p in params
                      if p.name not in (WINDOW_PARAM, ABSENT_PARAM)]
            type_params = [t for t in type_params
                           if t.name != RESULT_TYPE_PARAM]
        self_kind = None
        if params and params[0].name == "self":
            params = params[1:]
            if getattr(node, "self_mutable", False):
                self_kind = "borrows-var"
            elif is_borrows:
                # design 146 (DF-146b): a `borrows` accessor spelled `&self`
                # does NOT borrow its receiver shared-only. The window's flavor
                # is chosen at each use site — a read borrows shared, a write
                # borrows exclusively — so reporting "borrows" here would tell
                # a reader the opposite of the truth. `window` is the honest
                # answer, and the only receiver kind that means "it depends on
                # the caller".
                self_kind = "window"
            elif getattr(node, "self_is_reference", False):
                self_kind = "borrows"
            else:
                self_kind = "consumes"

        param_entries = []
        for p in params:
            entry = {"name": p.name, "label": p.name, "type": _type_str(p.type)}
            if p.default_value is not None:
                entry["default"] = _expr_str(p.default_value)
            if p.is_reference:
                entry["reference"] = "var" if p.reference_mutable else "shared"
            param_entries.append(entry)

        is_init = getattr(node, "is_init", False)
        name = node.name
        gen = _generics_str(type_params)
        # design 236: the static bit comes from the KEYWORD the author wrote,
        # not from the receiver's absence — which is what makes it renderable.
        # A `TraitMethod` spells it as `is_static`; a module-level `Function`
        # has neither field and is never static (it is not a method at all).
        is_static = bool(getattr(node, "declared_static", None)
                         if hasattr(node, "declared_static")
                         else getattr(node, "is_static", False))
        static_txt = "static " if is_static else ""
        head = ("init" if is_init else "%sfunc %s" % (static_txt, name)) + gen
        self_txt = {"borrows-var": "&var self", "borrows": "&self",
                    "window": "&self", "consumes": "self"}.get(self_kind)
        rendered = ([self_txt] if self_txt else [])
        for e in param_entries:
            text = "%s: %s" % (e["name"], e["type"])
            if "default" in e:
                text += " = " + e["default"]
            rendered.append(text)
        if is_borrows:
            place = getattr(node, "place_type", None)
            ret = _type_str(place)
            if getattr(node, "place_optional", False):
                ret += "?"
        else:
            ret = _type_str(node.return_type)
        # designs 136/141: the effects ride the post-parameter slot in the
        # canonical order `unsafe sync borrows` — so a rendered signature reads
        # exactly as the source spells it, and as the matching function TYPE
        # does. A borrows accessor's `sync` is implied by `borrows` (a place
        # window may not span a suspension) and the author never writes it, so
        # it is not rendered either.
        effect_txt = (" unsafe" if getattr(node, "is_unsafe", False) else "")
        if is_borrows:
            effect_txt += " borrows"
        elif getattr(node, "is_sync", False):
            effect_txt += " sync"
        ret_txt = "" if ret in (None, "Void") else " -> " + ret
        signature = "%s%s(%s)%s%s" % (_vis_prefix(visibility), head,
                                      ", ".join(rendered), effect_txt, ret_txt)

        return {
            "kind": "init" if is_init else "method" if owner else "func",
            "name": name,
            "signature": signature,
            "visibility": _visibility_str(visibility),
            "generics": _generics(type_params),
            "params": param_entries,
            "returns": ret,
            "effect": self._effect(node, owner, is_trait_method),
            "self": self_kind,
            "static": is_static,
            "doc": getattr(node, "doc", None),
            "line": node.line,
        }

    def _effect(self, node, owner: Optional[str], is_trait_method: bool) -> str:
        """The declaration's effects, space-separated. `suspending` when the
        effect graph says the body reaches a suspension point, else `sync`; an
        `unsafe` declaration (design 130) prefixes that with `unsafe`, so a safe
        declaration's value is unchanged."""
        suspension = self._suspension_effect(node, owner, is_trait_method)
        if getattr(node, "is_unsafe", False):
            return "unsafe " + suspension
        return suspension

    def _suspension_effect(self, node, owner: Optional[str],
                           is_trait_method: bool) -> str:
        """`suspending` when the effect graph says the body reaches a suspension
        point, else `sync`. A declared `sync func` is sync by definition — the
        checker already proved the body suspension-free."""
        if getattr(node, "is_sync", False):
            return "sync"
        # The program's own effect graph is the authority (design 122 unit E).
        # It answers for every USER function and method now that the docs path
        # runs the whole-program fixpoint; before that it was always empty here,
        # so a suspending user function was reported `sync`.
        nodes = getattr(self.typechecker, "_suspend_nodes", {}) or {}
        if owner is not None and not is_trait_method:
            entry = nodes.get(node.node_id)
        else:
            entry = nodes.get(("fn", getattr(node, "mangled_symbol", None)
                               or node.name))
        if entry is not None:
            return "suspending" if getattr(entry, "suspends", False) else "sync"
        # No node: a std body, which THIS typechecker never checks (std is
        # pre-checked by the builtin typechecker, design 84). Its finalized graph
        # is carried over as these two sets — effect-graph facts too, just from
        # the other graph.
        if owner is not None and not is_trait_method:
            if (owner, node.name) in self._std_suspending_methods:
                return "suspending"
        elif owner is None and node.name in self._std_suspending_functions:
            return "suspending"
        return "sync"


def build_docs(ctx: Dict[str, Any], include_private: bool = False) -> Dict[str, Any]:
    return DocsBuilder(ctx, include_private).build()


def render_docs(docs: Dict[str, Any]) -> str:
    """Pretty JSON with stable key order — the file is meant to be diffed."""
    return json.dumps(docs, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
