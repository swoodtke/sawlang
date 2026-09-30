#!/usr/bin/env python3
"""The std cone of sawc2: every std declaration Stage 0's build compiles into it.

    python compiler/tools/std_cone.py              # fails if std_cone.txt is stale
    python compiler/tools/std_cone.py --write      # rewrites std_cone.txt
    python compiler/tools/std_cone.py --instances  # prints every instance in full
    python compiler/tools/std_cone.py --why TEXT   # how the build reaches a declaration
    python compiler/tools/std_cone.py --rules      # the subset rules that fire in the cone
    python compiler/tools/std_cone.py --entry FILE # the cone of another program

The frozen compiler builds `compiler/driver` as `build.py` does, in a child
process with its code generator observed, and stops once the unoptimized module
exists. Each runtime object a hosted link adds is observed the same way. The
cone is what the linked program reaches from `main` in those modules' symbol
graph, mapped back to the declarations whose bodies define the symbols, closed
over the types and traits those bodies name. SL:architecture §4 ("The bootstrap
std") says why; `std_cone_review.md` says what the method cannot see.
"""
import argparse
import concurrent.futures
import dataclasses
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import build  # noqa: E402

CONE_FILE = os.path.join(HERE, "std_cone.txt")
OUT_DIR = os.path.join(REPO, ".build", "std-cone")
SHIM_C = os.path.join(REPO, "sawc", "rt", "shim.c")
TIMEOUT = 600
# The cone is recorded for one hosted target, whatever host runs the lane, so
# the file never depends on where it was written: the macOS arm64 build, which
# links the host_macos runtime. No object is emitted, so any host can observe it.
TARGET = "arm64-apple-darwin"
OBSERVE_FLAG = "--observe"

# A declaration's module, from its file: std's own modules, the prelude's
# built-in traits, and the runtime's sources. Matched on the path's tail so a
# std cache written from another checkout still maps.
_MODULE_RE = re.compile(r"(?:^|/)sawc/(std/.+|builtin|rt/.+)\.saw$")
# `Header$m$dep` is a type's module-qualified identity; the part before `$m$`
# is the name its author wrote.
_IDENTITY_SUFFIX = "$m$"
_CLOSURE_PREFIX = "__closure$"
_SYMBOL_REF = re.compile(r'@(?:"((?:[^"\\]|\\.)*)"|([-a-zA-Z$._][-a-zA-Z$._0-9]*))')
DERIVED_TRAITS = (("is_derived_copy", "Copy"), ("is_derived_equals", "Equatable"),
                  ("is_derived_compare", "Comparable"), ("is_derived_hash", "Hashable"),
                  ("is_derived_serialize", "Serialize"),
                  ("is_derived_deserialize", "Deserialize"))
OWNING, PLAIN = "(owning)", "(plain)"


def module_of(path):
    """`std.vector`, `builtin`, `rt.common.mem`; None outside std and the runtime."""
    m = _MODULE_RE.search((path or "").replace(os.sep, "/"))
    return m.group(1).replace("/", ".") if m else None


def written_name(identity):
    return (identity or "").split(_IDENTITY_SUFFIX)[0]


# ---------------------------------------------------------------- the observer
# Runs inside the child process, with `sawc/` on the path. Nothing here edits
# the frozen compiler: the hooks wrap its methods for this one process.

class _Stop(BaseException):
    """Raised once the module is generated: nothing past codegen matters, and a
    BaseException passes the codegen wrapper that reports an `Exception`."""


class Observer:
    def __init__(self, A, ast_walk):
        self.A = A
        self.walk_children = ast_walk.child_nodes
        self.decls = {}        # decl id -> {module, kind, name}
        self.by_position = {}  # (module, line, column) -> decl record
        self.types = {}        # identity or name -> decl id
        self.traits = {}       # name or identity -> Trait node
        self.trait_ids = {}    # Trait node id -> decl id
        self.type_nodes = {}   # decl id -> Struct or Enum node
        self.alias_nodes = {}  # decl id -> TypeDefinition node
        self.conformances = {}  # type identity -> [trait names]
        self.externs = {}      # symbol -> [extern decl id], one per declaring module
        self.statics = {}      # LLVM global name -> decl id
        self.bodies = {}       # LLVM symbol -> {decl, instance, uses}
        self.defaults = {}     # (module, line, column, name) -> Extension
        self.compiler_types = set()  # identities of the types the compiler source declares
        self.unresolved = []
        self.stack = []

    # -- the declaration index, built from the merged program before any body
    def index(self, program):
        progs = [program]
        for md in program.module_decls or []:
            if md.body is not None:
                progs.append(md.body)
        for prog in progs:
            for s in list(prog.structs) + list(prog.enums):
                self._index_type(s)
            for t in prog.traits:
                self._index_trait(t)
            for td in prog.type_definitions:
                mod = module_of(td.source_file)
                if mod:
                    did = self._declare(mod, "type", td.name, td)
                    self.types[td.type_identity or td.name] = did
                    self.types.setdefault(td.name, did)
                    self.alias_nodes[did] = td
        for prog in progs:
            for fn in prog.functions:
                if fn.is_mono_instance:
                    continue
                self._index_callable(fn, None, "func", fn.name)
            for ext in prog.extensions:
                self._index_extension(ext)
            for st in prog.statics:
                mod = module_of(st.source_file)
                if mod:
                    self._declare(mod, "static", st.name, st)
            for block in prog.extern_blocks:
                for ef in block.functions:
                    mod = module_of(ef.source_file)
                    if mod:
                        did = self._declare(mod, "extern", ef.name, ef)
                        dids = self.externs.setdefault(ef.name, [])
                        if did not in dids:
                            dids.append(did)
        self._overload_signatures()

    def _declare(self, module, kind, name, node=None):
        """A declaration's id, recording where it is written for `--rules`."""
        did = "%s|%s|%s" % (module, kind, name)
        where = [getattr(node, "line", 0) or 0, getattr(node, "column", 0) or 0]
        self.decls.setdefault(did, {"module": module, "kind": kind, "name": name,
                                    "at": where})
        return did

    def _index_type(self, node):
        mod = module_of(node.source_file)
        identity = node.type_identity or node.name
        if not mod:
            return
        kind = "struct" if isinstance(node, self.A.Struct) else "enum"
        did = self._declare(mod, kind, node.name, node)
        self.types[identity] = did
        self.types.setdefault(node.name, did)
        self.type_nodes[did] = node

    def _index_trait(self, node):
        mod = module_of(node.source_file)
        self.traits[node.type_identity or node.name] = node
        self.traits.setdefault(node.name, node)
        if not mod:
            return
        did = self._declare(mod, "trait", node.name, node)
        self.trait_ids[id(node)] = did
        for tm in node.methods:
            if tm.body is not None:
                self._index_callable(tm, None, "default", "%s.%s" % (node.name, tm.name),
                                     owner_trait=node, module=mod)

    def _index_extension(self, ext):
        owner = written_name(ext.type_identity or ext.struct_name)
        if ext.methods and all(m.is_mono_instance for m in ext.methods):
            return
        identity = ext.type_identity or ext.struct_name
        self.conformances.setdefault(identity, []).extend(ext.conformances)
        mod = module_of(ext.source_file)
        for m in ext.methods:
            if mod and (m.line, m.column) == (ext.line, ext.column):
                # A member the conformance takes from a trait's default body is
                # spliced in at the extension's own position.
                self.defaults[(mod, m.line, m.column, m.name)] = ext
                continue
            # The exclusive twin of a `borrows` accessor shares its authored
            # declaration's position and is that declaration (`body` maps it).
            if m.is_mono_instance or m.is_synthesized or _derived(m) or m.place_var_twin:
                continue
            if m.is_init:
                kind = "init"
            elif m.is_static:
                kind = "static-method"
            else:
                kind = "method"
            self._index_callable(m, ext, kind, "%s.%s" % (owner, m.name))

    def _index_callable(self, node, ext, kind, qualname, owner_trait=None, module=None):
        mod = module or module_of(node.source_file)
        if not mod:
            return
        key = (mod, node.line, node.column)
        record = {"node": node, "ext": ext, "kind": kind, "qualname": qualname,
                  "trait": owner_trait, "module": mod, "did": None}
        if key in self.by_position and self.by_position[key]["node"] is not node:
            # Two declarations at one position would make positions ambiguous
            # as template identities; the tool refuses rather than guesses.
            self.unresolved.append("two declarations at %s:%d:%d" % key)
        self.by_position[key] = record

    def _overload_signatures(self):
        """An overloaded name carries its signature, so each member stays one
        declaration; an `init` always carries its labels (§3.0's stable path)."""
        groups = {}
        for rec in self.by_position.values():
            groups.setdefault((rec["module"], rec["kind"], rec["qualname"]), []).append(rec)
        for (mod, kind, qualname), recs in sorted(groups.items(), key=lambda kv: kv[0]):
            for rec in recs:
                name = qualname
                if kind == "init" or len(recs) > 1:
                    name += self._signature(rec["node"], typed=len(recs) > 1)
                rec["did"] = self._declare(mod, kind, name, rec["node"])

    def _signature(self, node, typed):
        parts = []
        for p in node.parameters:
            if p.name == "self":
                continue
            parts.append("%s: %s" % (p.name, self.render(p.type)) if typed else p.name + ":")
        return "(%s)" % (", ".join(parts) if typed else "".join(parts))

    # -- types
    def render(self, t, classify=None):
        """A type in source spelling, a module-qualified identity reduced to its
        written name. With `classify`, a type the compiler source declares is
        rendered as its ownership class instead."""
        A = self.A
        if t is None:
            return "?"
        k = t.kind
        if k in (A.TypeKind.STRUCT, A.TypeKind.ENUM):
            ident = t.struct_name if k == A.TypeKind.STRUCT else t.enum_name
            if classify is not None and ident not in self.types and ident in classify.decl_names:
                return OWNING if classify.owning(t) else PLAIN
            args = t.type_args or []
            name = written_name(ident)
            if args:
                return "%s<%s>" % (name, ", ".join(self.render(a, classify) for a in args))
            return name
        if k == A.TypeKind.OPTIONAL:
            return self.render(t.inner_type, classify) + "?"
        if k == A.TypeKind.REFERENCE:
            return ("&var " if t.reference_mutable else "&") + self.render(t.inner_type, classify)
        if k == A.TypeKind.TUPLE:
            return "(%s)" % ", ".join(self.render(e, classify) for e in t.element_types or [])
        if k == A.TypeKind.POINTER:
            return "%s<%s>" % ("UnsafePointer" if t.pointer_mutable else "UnsafeConstPointer",
                               self.render(t.inner_type, classify))
        if k == A.TypeKind.ARRAY:
            return "[%s; %s]" % (self.render(t.array_element_type, classify), t.array_size)
        if k == A.TypeKind.FUNCTION:
            return "(%s) -> %s" % (", ".join(self.render(p, classify) for p in t.param_types or []),
                                   self.render(t.func_return_type, classify))
        return str(t)

    def type_uses(self, t, out):
        """The std types and traits a type names, at any depth."""
        A = self.A
        stack = [t]
        while stack:
            t = stack.pop()
            if t is None or not isinstance(t, A.SawType):
                continue
            k = t.kind
            if k == A.TypeKind.STRUCT and t.struct_name in self.types:
                out.add(self.types[t.struct_name])
            elif k == A.TypeKind.ENUM and t.enum_name in self.types:
                out.add(self.types[t.enum_name])
            elif k == A.TypeKind.EXISTENTIAL:
                self.trait_use(t.existential_trait, out)
            stack.extend(t.type_args or [])
            stack.extend(t.element_types or [])
            stack.extend(t.param_types or [])
            stack.extend([t.inner_type, t.array_element_type, t.func_return_type])

    def trait_use(self, name, out):
        node = self.traits.get(name) or self.traits.get(written_name(name))
        if node is not None and id(node) in self.trait_ids:
            out.add(self.trait_ids[id(node)])

    def node_uses(self, root, out):
        """The std types and traits a declaration's signature and body name:
        every `SawType` any node carries, annotations included."""
        stack = [root]
        seen = set()
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            if dataclasses.is_dataclass(node):
                for f in dataclasses.fields(node):
                    self._value_types(getattr(node, f.name, None), out)
            stack.extend(self.walk_children(node))
        for p in getattr(root, "parameters", None) or []:
            self.type_uses(p.type, out)

    def _value_types(self, value, out):
        if isinstance(value, self.A.SawType):
            self.type_uses(value, out)
        elif isinstance(value, (list, tuple)):
            for v in value:
                if isinstance(v, (self.A.SawType, list, tuple)):
                    self._value_types(v, out)
        elif isinstance(value, self.A.Parameter):
            self.type_uses(value.type, out)

    def type_closure(self):
        """{type or trait decl id: the decl ids it needs}: a struct's field
        types, an enum's payload types, the marker traits a type conforms to,
        and a trait's parents."""
        out = {}
        for did, node in self.type_nodes.items():
            uses = set()
            for f in getattr(node, "fields", None) or []:
                self.type_uses(f.type, uses)
            for v in getattr(node, "variants", None) or []:
                for _, t in v.associated_types:
                    self.type_uses(t, uses)
            for tp in node.type_params or []:
                for b in tp.bounds:
                    self.trait_use(b, uses)
            for trait in self.conformances.get(node.type_identity or node.name, []):
                tnode = self.traits.get(trait)
                if tnode is not None and not self._requirements(tnode):
                    self.trait_use(trait, uses)
            uses.discard(did)
            out[did] = sorted(uses)
        for did, td in self.alias_nodes.items():
            uses = set()
            self.type_uses(td.defined_type, uses)
            uses.discard(did)
            out[did] = sorted(uses)
        for tnode in self.traits.values():
            did = self.trait_ids.get(id(tnode))
            if did is None or did in out:
                continue
            uses = set()
            for parent in tnode.parent_traits:
                self.trait_use(parent, uses)
            out[did] = sorted(uses)
        return out

    def _requirements(self, trait, seen=None):
        """Every method name a trait and its parents declare."""
        seen = seen if seen is not None else set()
        if id(trait) in seen:
            return set()
        seen.add(id(trait))
        names = {m.name for m in trait.methods}
        for parent in trait.parent_traits:
            p = self.traits.get(parent)
            if p is not None:
                names |= self._requirements(p, seen)
        return names

    # -- bodies
    def body(self, codegen, owner, node):
        """Record the declaration behind the body being generated now."""
        if not self.stack:
            return
        symbol = self.stack[-1]
        mod = module_of(node.source_file)
        owner_base = owner
        if owner is not None:
            base = codegen.mono_struct_args.get(owner) or codegen.mono_enum_args.get(owner)
            owner_base = base[0] if base else owner
        record = None
        if mod is not None:
            record = self.by_position.get((mod, node.line, node.column))
            ext = self.defaults.get((mod, node.line, node.column, node.name))
            if ext is not None:
                record = self.default_record(ext, node.name)
        uses = set()
        entry = {"decl": None, "instance": None, "uses": []}
        derived = [trait for flag, trait in DERIVED_TRAITS if getattr(node, flag, False)]
        synthesized = bool(getattr(node, "is_synthesized", False)) or bool(derived)
        if synthesized:
            type_did = self.types.get(owner_base) if owner_base else None
            if type_did is not None:
                tmod = self.decls[type_did]["module"]
                entry["decl"] = self._declare(tmod, "synthesized", "%s.%s" % (
                    written_name(owner_base), node.name), node)
                uses.add(type_did)
                for trait in derived:
                    self.trait_use(trait, uses)
        elif record is not None and self._same_declaration(record["node"], node):
            entry["decl"] = record["did"]
            template = record["node"]
            if record["trait"] is not None:
                uses.add(self.trait_ids[id(record["trait"])])
            if record["ext"] is not None:
                for trait in record["ext"].conformances:
                    tnode = self.traits.get(trait)
                    if tnode is not None and node.name in self._requirements(tnode):
                        self.trait_use(trait, uses)
                for tp in record["ext"].type_params or []:
                    for b in tp.bounds:
                        self.trait_use(b, uses)
            for tp in getattr(template, "type_params", None) or []:
                for b in tp.bounds:
                    self.trait_use(b, uses)
            if getattr(node, "is_mono_instance", False):
                entry["instance"] = self.instance(codegen, symbol, owner, record)
        elif mod is not None:
            self.unresolved.append("%s: a body of %s.%s at %s:%d:%d matches no declaration"
                                   % (symbol, owner_base, node.name, mod, node.line, node.column))
        if owner_base in self.types:
            uses.add(self.types[owner_base])
        self.node_uses(node, uses)
        entry["uses"] = sorted(uses)
        self.bodies[symbol] = entry

    def default_record(self, ext, name):
        """The trait default body a conformance's spliced member comes from."""
        stack = list(ext.conformances)
        seen = set()
        while stack:
            trait = self.traits.get(stack.pop(0))
            if trait is None or id(trait) in seen:
                continue
            seen.add(id(trait))
            for tm in trait.methods:
                if tm.name == name and tm.body is not None:
                    mod = module_of(trait.source_file)
                    return self.by_position.get((mod, tm.line, tm.column))
            stack.extend(trait.parent_traits)
        return None

    def _same_declaration(self, template, node):
        if template is node:
            return True
        if template.name == node.name:
            return True
        # The exclusive twin of a `borrows` accessor is one authored declaration.
        return bool(getattr(node, "place_var_twin", False))

    def instance(self, codegen, symbol, owner, record):
        """[(parameter, full rendering, classified rendering)] of an instance."""
        registry = getattr(codegen, "mono_registry", None)
        pairs = []
        if owner is not None:
            base = codegen.mono_struct_args.get(owner) or codegen.mono_enum_args.get(owner)
            if base is not None:
                decl = self.type_nodes.get(self.types.get(base[0]))
                names = [tp.name for tp in (decl.type_params if decl is not None else [])]
                pairs += list(zip(names, base[1]))
        inst = registry.instances.get(symbol) if registry is not None else None
        template = record["node"]
        names = [tp.name for tp in getattr(template, "type_params", None) or []]
        if inst is not None and inst.kind == "fn":
            pairs += list(zip(names, inst.args))
        elif inst is not None and inst.kind == "method" and inst.method_args:
            pairs += list(zip(names, inst.method_args))
        classify = Classifier(codegen, self)
        return [(n, self.render(t), self.render(t, classify)) for n, t in pairs]


class Classifier:
    """Whether a compiler-source type owns memory, which is what the
    instance-dependent hazard faces turn on (SL:hazards S3, S23)."""

    def __init__(self, codegen, observer):
        self.codegen = codegen
        self.decl_names = observer.compiler_types

    def owning(self, t):
        return bool(self.codegen._needs_cleanup(t))


def _derived(m):
    return any(getattr(m, flag, False) for flag, _ in DERIVED_TRAITS)


def observe(out_path, sawc_argv):
    """Run the frozen compiler in this process and write what codegen emitted."""
    sys.path.insert(0, os.path.join(REPO, "sawc"))
    import ast_nodes as A
    import ast_walk
    import codegen.core as CC
    obs = Observer(A, ast_walk)
    result = {}
    cls = CC.CodeGenerator

    orig_defer = cls._defer_body

    def defer(self, llvm_func, thunk):
        name = llvm_func.name

        def run():
            obs.stack.append(name)
            try:
                return thunk()
            finally:
                obs.stack.pop()
        return orig_defer(self, llvm_func, run)
    cls._defer_body = defer

    def hook(method_name, owned):
        orig = getattr(cls, method_name)

        def hooked(self, *args, **kwargs):
            owner, node = (args[0], args[1]) if owned else (None, args[0])
            obs.body(self, owner, node)
            return orig(self, *args, **kwargs)
        setattr(cls, method_name, hooked)
    hook("_generate_function", False)
    hook("_generate_method", True)
    hook("_generate_init_method", True)
    hook("_generate_static_method", True)

    orig_static = cls._emit_static_global

    def emit_static(self, static):
        before = set(self.module.globals)
        value = orig_static(self, static)
        mod = module_of(static.source_file)
        if mod:
            for name in set(self.module.globals) - before:
                obs.statics[name] = obs._declare(mod, "static", static.name)
        return value
    cls._emit_static_global = emit_static

    orig_generate = cls.generate

    def generate(self, program):
        obs.index(program)
        for s in list(program.structs) + list(program.enums):
            if not module_of(s.source_file):
                obs.compiler_types.add(s.type_identity or s.name)
        orig_generate(self, program)
        result.update(graph(self.module))
        raise _Stop()
    cls.generate = generate

    import sawc as frozen
    sys.argv = ["sawc.py"] + list(sawc_argv)
    status = "no module"
    try:
        frozen.main()
    except _Stop:
        status = "ok"
    except SystemExit as e:
        status = "exit %s" % (e.code,)
    result.update(status=status, decls=obs.decls, bodies=obs.bodies,
                  statics=obs.statics, externs=obs.externs,
                  type_uses=obs.type_closure() if status == "ok" else {},
                  unresolved=obs.unresolved)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, sort_keys=True)
    return 0


def graph(module):
    """Every symbol the module defines or declares, with the symbols each
    definition refers to, read from its unoptimized text."""
    symbols = {}
    # A reference is only to a symbol the module declares or defines: the text
    # scan also meets `@name` inside string data, which names nothing.
    names = {gv.name for gv in module.global_values}
    for gv in module.global_values:
        defined = bool(getattr(gv, "blocks", None)) or getattr(gv, "initializer", None) is not None
        refs = []
        if defined:
            for m in _SYMBOL_REF.finditer(str(gv)):
                ref = m.group(2) if m.group(1) is None else m.group(1)
                if ref != gv.name and ref in names:
                    refs.append(ref)
        symbols[gv.name] = {"defined": defined,
                            "external": gv.linkage not in ("internal", "private"),
                            "function": hasattr(gv, "blocks"),
                            "refs": sorted(set(refs))}
    return {"symbols": symbols}


# ---------------------------------------------------------------- the cone
@dataclasses.dataclass
class Build:
    name: str       # `sawc2`, or the runtime source's module
    argv: list
    out_dir: str
    records: dict = None


def builds(entry, out_dir):
    """sawc2, or the program `entry`, and every runtime object a hosted link
    of it adds, all for `TARGET`."""
    sys.path.insert(0, os.path.join(REPO, "sawc"))
    import rt_build
    target = ["--target", TARGET]
    out = [Build("sawc2", build.sawc_arguments(entry or build.DRIVER_ENTRY,
                                               os.path.join(out_dir, "sawc2")) + target,
                 out_dir)]
    sources, _ = rt_build._runtime_sources(TARGET)
    for src in sources:
        name = module_of(src)
        out.append(Build(name, [src, "-o", os.path.join(out_dir, name + ".o"),
                                "--runtime-build"] + target, out_dir))
    return out


def run_observer(b):
    os.makedirs(b.out_dir, exist_ok=True)
    out = os.path.join(b.out_dir, b.name + ".json")
    cmd = [sys.executable, os.path.abspath(__file__), OBSERVE_FLAG, out, "--"] + b.argv
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    output = (r.stdout + r.stderr).strip()[-2000:]
    if not os.path.exists(out):
        return b, None, output
    with open(out, encoding="utf-8") as fh:
        records = json.load(fh)
    return b, records, None if records.get("status") == "ok" else output


def shim_functions():
    names = set()
    with open(SHIM_C, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\(", line)
            if m and not line.rstrip().endswith(";"):
                names.add(m.group(1))
    return names


@dataclasses.dataclass
class Cone:
    decls: dict            # decl id -> {module, kind, name}
    reached: dict          # decl id -> "sawc2" | "runtime"
    instances: dict        # decl id -> {(classified tuple)}
    full_instances: dict   # decl id -> {(full tuple)}
    helpers: dict          # compiler-emitted helper -> "sawc2" | "runtime"
    externals: dict        # unresolved symbol -> "shim.c" | "host"
    problems: list
    why: dict = None       # decl id -> what first reached it


def compute(results):
    """The cone, from each build's observed module."""
    problems = []
    decls = {}
    for b in results:
        if b.records is None or b.records.get("status") != "ok":
            problems.append("std cone: the %s build was not observed: %s"
                            % (b.name, (b.records or {}).get("status", "no output")))
            continue
        decls.update(b.records["decls"])
        problems += ["std cone: %s: %s" % (b.name, u) for u in b.records["unresolved"]]
    if problems:
        return Cone(decls, {}, {}, {}, {}, {}, problems)
    exported = {}
    for b in results:
        for sym, info in b.records["symbols"].items():
            if info["defined"] and info["external"]:
                exported.setdefault(sym, b.name)
    by_name = {b.name: b for b in results}
    shim = shim_functions()

    def resolve(obj, sym):
        info = by_name[obj].records["symbols"].get(sym)
        if info is not None and info["defined"]:
            return (obj, sym)
        if sym in exported:
            return (exported[sym], sym)
        return (None, sym)

    reached = {}
    instances, full = {}, {}
    helpers, externals = {}, {}
    type_uses = {}
    for b in results:
        for did, uses in b.records["type_uses"].items():
            type_uses.setdefault(did, set()).update(uses)

    why = {}

    def reach(did, tag, parent):
        if did not in reached:
            reached[did] = tag
            why[did] = parent

    def visit(roots, only_sawc2, tag):
        """Depth-first over the symbol graph from `roots`, in sorted order, so
        the first path to a declaration (`--why`) is the same every run."""
        seen = set()
        stack = [(r, None) for r in reversed(roots)]
        while stack:
            node, parent = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            obj, sym = node
            label = "%s:%s" % (obj, sym)
            why.setdefault(label, parent)
            if obj is None:
                if not sym.startswith("llvm."):
                    externals.setdefault(sym, "shim.c" if sym in shim else "host")
                continue
            rec = by_name[obj].records
            body = body_of(rec["bodies"], sym)
            module = None
            if body is not None:
                did = body["decl"]
                if did is not None:
                    module = decls[did]["module"]
                    reach(did, tag, parent)
                    if body["instance"]:
                        instances.setdefault(did, set()).add(
                            tuple("%s=%s" % (n, c) for n, _, c in body["instance"]))
                        full.setdefault(did, set()).add(
                            tuple("%s=%s" % (n, f) for n, f, _ in body["instance"]))
                for use in body["uses"]:
                    reach(use, tag, label)
            elif sym in rec["statics"]:
                reach(rec["statics"][sym], tag, parent)
            elif rec["symbols"][sym]["function"]:
                helpers.setdefault(helper_name(sym), tag)
            for ref in reversed(rec["symbols"][sym]["refs"]):
                for did in extern_decls(rec["externs"].get(ref), module, decls):
                    reach(did, tag, label)
                target = resolve(obj, ref)
                if only_sawc2 and target[0] not in (None, "sawc2"):
                    continue
                stack.append((target, label))
        return seen

    visit([("sawc2", "main")], True, "sawc2")
    visit([("sawc2", "main")], False, "runtime")
    pending = sorted(reached)
    while pending:
        did = pending.pop(0)
        for use in sorted(type_uses.get(did, ())):
            if use not in reached:
                reach(use, reached[did], did)
                pending.append(use)
    missing = sorted(d for d in reached if d not in decls)
    problems += ["std cone: no declaration record for %s" % d for d in missing]
    return Cone(decls, reached, instances, full, helpers, externals, problems, why)


def extern_decls(dids, module, decls):
    """The extern declaration a reference from a body in `module` goes through:
    that module's own. A compiler-emitted helper or a compiler-source body names
    the symbol through no std declaration."""
    return [d for d in dids or () if decls[d]["module"] == module]


def body_of(bodies, sym):
    """A symbol's body record; a closure belongs to the body it is written in."""
    while True:
        if sym in bodies:
            return bodies[sym]
        if not sym.startswith(_CLOSURE_PREFIX):
            return None
        inner = sym[len(_CLOSURE_PREFIX):]
        # `__closure$<enclosing symbol>$<line>_<column>[$n]`: drop the suffix.
        parts = inner.split("$")
        while parts and re.fullmatch(r"\d+_\d+|\d+", parts[-1]):
            parts.pop()
        sym = "$".join(parts)
        if not sym:
            return None


def helper_name(sym):
    """A compiler-emitted helper, its per-format-shape variants collapsed."""
    m = re.match(r"(__saw_panic\$\w+\$)", sym)
    return m.group(1) + "*" if m else sym


def render(cone):
    """std_cone.txt: one line per declaration, grouped by module and sorted."""
    groups = {}
    for did, via in cone.reached.items():
        d = cone.decls[did]
        groups.setdefault(d["module"], []).append((d["name"], d["kind"], did, via))
    total = sum(len(v) for v in groups.values())
    lines = [
        "# The std cone of sawc2: every std and runtime declaration whose body, type or",
        "# trait Stage 0's build of compiler/driver for %s compiles into it" % TARGET,
        "# (SL:architecture §4; the method and its blind spots: std_cone_review.md).",
        "# Written by compiler/tools/std_cone.py --write; compiler/tests/run.py fails when",
        "# the build's cone differs from this file. `via runtime` marks what only the",
        "# runtime objects reach; an `instance` line is one type-argument tuple, a type",
        "# the compiler source declares written as (owning) or (plain).",
        "# %d declarations in %d modules" % (total, len(groups)),
    ]
    for mod in sorted(groups):
        entries = sorted(groups[mod])
        lines.append("")
        lines.append("%s: %d" % (mod, len(entries)))
        for name, kind, did, via in entries:
            lines.append("  %s %s%s" % (kind, name, "  via runtime" if via == "runtime" else ""))
            for inst in sorted(cone.instances.get(did, ())):
                lines.append("    instance " + ", ".join(inst))
    for title, table in (("compiler-emitted IR helpers", cone.helpers),
                         ("external C symbols", cone.externals)):
        lines.append("")
        lines.append("(%s): %d" % (title, len(table)))
        for name in sorted(table):
            tag = table[name]
            suffix = {"runtime": "  via runtime", "shim.c": "  shim.c"}.get(tag, "")
            lines.append("  %s%s" % (name, suffix))
    return "\n".join(lines) + "\n"


def cone(entry=None):
    """(rendered cone, problems, Cone) of sawc2, or of the program `entry`:
    observes every build, in parallel, in a directory of its own so that two
    runs never read each other's records."""
    os.makedirs(OUT_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=OUT_DIR) as out_dir:
        todo = builds(entry, out_dir)
        workers = min(len(todo), os.cpu_count() or 1)
        failures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for b, records, error in pool.map(run_observer, todo):
                b.records = records
                if error:
                    failures.append("std cone: the %s build failed: %s" % (b.name, error))
    if failures:
        return None, failures, None
    c = compute(todo)
    if c.problems:
        return None, c.problems, c
    return render(c), [], c


# ---------------------------------------------------------------- the review
# The subset checker's rules, run over the cone's own bodies for
# std_cone_review.md: what fires there is either a trust obligation or, for the
# rules that encode only the compiler source's discipline, fires by design.

DISCIPLINE_RULES = ("import-allowlist", "std-api", "borrows-accessor", "borrow-syntax",
                    "test-directive", "closure-capture")
# The rules that judge a file rather than a declaration, reported for every
# module in the cone.
FILE_RULES = ("lex", "parse", "file-end", "workaround-marker", "selective-imports",
              "import-allowlist", "inline-module")


def module_path(module):
    """The source file of a cone module: the inverse of `module_of`."""
    return os.path.join(REPO, "sawc", *module.split(".")) + ".saw"


def _extents(SC, program):
    """{(line, column): (first line, last line)} of every declaration in a file,
    a body's last line being the last line any node inside it sits on."""
    out = {}

    def span(node, extra=()):
        lines = [n.line for n in SC.walk(node) if getattr(n, "line", 0)]
        lines += [x for x in extra if x]
        return (node.line, max(lines) if lines else node.line)

    for prog in SC.programs(program):
        for fn in prog.functions:
            out[(fn.line, fn.column)] = span(fn)
        for ext in prog.extensions:
            for m in ext.methods:
                out[(m.line, m.column)] = span(m)
            # An extension head belongs to the type it extends.
            out[("extension", ext.line)] = (ext.line, ext.line, ext.struct_name)
        for tr in prog.traits:
            out[(tr.line, tr.column)] = (tr.line, tr.line)
            for tm in tr.methods:
                out[(tm.line, tm.column)] = span(tm)
        for st in prog.statics:
            out[(st.line, st.column)] = span(st)
        for decl in prog.structs:
            out[(decl.line, decl.column)] = span(decl, [f.line for f in decl.fields])
        for decl in prog.enums + prog.type_definitions:
            out[(decl.line, decl.column)] = span(decl)
        for block in prog.extern_blocks:
            for ef in block.functions:
                out[(ef.line, ef.column)] = span(ef)
    return out


def rule_firings(c):
    """[(rule, decl id, file:line, message)] for every subset rule that fires
    inside a cone declaration: the source rules per file, the build rules with
    each file as its own build, and `owned-operand` as Stage 0's own code
    generator judges sawc2's build, generic bodies at each instantiation."""
    import subset_check as SC
    std = SC.std_facts()
    by_file = {}
    types = {}
    for did in c.reached:
        by_file.setdefault(module_path(c.decls[did]["module"]), []).append(did)
        if c.decls[did]["kind"] in ("struct", "enum"):
            types[c.decls[did]["name"]] = did
    firings = []
    ranges = {}
    for path in sorted(by_file):
        src = SC.SourceFile(path)
        extents = _extents(SC, src.program)
        spans = []
        for did in by_file[path]:
            at = tuple(c.decls[did]["at"])
            if at in extents and c.decls[did]["kind"] != "synthesized":
                spans.append((extents[at], did))
        for key, value in extents.items():
            if key[0] == "extension":
                owner = types.get(written_name(value[2]))
                if owner is not None:
                    spans.append(((value[0], value[1]), owner))
        ranges[path] = spans
        diags = SC.FileChecker(src, std, SC.BuildFacts([src])).run()
        diags += [d for d in SC.check_build([src], [], std)
                  if not (d.rule == "program-unique-names" and src.rel in d.message)]
        for d in diags:
            did = _innermost(spans, d.line)
            if did is not None:
                firings.append((d.rule, did, "%s:%d" % (src.rel, d.line), d.message))
            elif d.rule in FILE_RULES:
                firings.append((d.rule, module_of(path), "%s:%d" % (src.rel, d.line),
                                d.message))
    compiled, output, sites = SC.generated_build(build.DRIVER_ENTRY)
    if not compiled:
        raise RuntimeError("std cone: the owned-operand compile failed: " + output[-500:])
    for path, line, position, kind in sorted(set(sites)):
        spans = ranges.get(os.path.abspath(path)) if path else None
        did = _innermost(spans or [], line)
        if did is not None:
            firings.append(("owned-operand", did, "%s:%d" % (os.path.relpath(path, REPO), line),
                            SC.GENERATED_MESSAGES[kind].split(";")[0] % position))
    return sorted(set(firings))


def _innermost(spans, line):
    best = None
    for (first, last), did in spans:
        if first <= line <= last and (best is None or last - first < best[0]):
            best = (last - first, did)
    return best[1] if best else None


def print_rules(c):
    firings = rule_firings(c)
    for rule, did, where, message in firings:
        d = c.decls.get(did) or {"kind": "module", "name": did}
        group = "discipline" if rule in DISCIPLINE_RULES else "hazard"
        print("%s\t%s\t%s %s\t%s\t%s" % (group, rule, d["kind"], d["name"], where, message))


def diff_lines(expected, got):
    exp, new = set(expected.splitlines()), set(got.splitlines())
    added = [l for l in got.splitlines() if l not in exp]
    removed = [l for l in expected.splitlines() if l not in new]
    return added, removed


def check():
    """([failure], {count: n}) for the runner: the build's cone against the file."""
    text, problems, _ = cone()
    if problems:
        return problems, {}
    try:
        with open(CONE_FILE, encoding="utf-8") as fh:
            expected = fh.read()
    except FileNotFoundError:
        expected = ""
    if text == expected:
        return [], {"std cone declarations": _declaration_count(text)}
    added, removed = diff_lines(expected, text)
    out = ["std cone: %s differs from the build's cone; review the change, rerun "
           "`compiler/tools/std_cone.py --write` and commit the file"
           % os.path.relpath(CONE_FILE, REPO)]
    out += ["std cone: reached, not listed: %s" % l.strip() for l in added[:40]]
    out += ["std cone: listed, not reached: %s" % l.strip() for l in removed[:40]]
    if len(added) > 40 or len(removed) > 40:
        out.append("std cone: %d more lines differ" % (max(len(added), len(removed)) - 40))
    return out, {}


def _declaration_count(text):
    m = re.search(r"^# (\d+) declarations", text, re.M)
    return int(m.group(1)) if m else 0


def main(argv):
    if len(argv) >= 3 and argv[0] == OBSERVE_FLAG and argv[2] == "--":
        return observe(argv[1], argv[3:])
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="rewrite std_cone.txt")
    ap.add_argument("--instances", action="store_true",
                    help="print every instance's type arguments in full")
    ap.add_argument("--why", metavar="TEXT",
                    help="print how the build first reaches each declaration naming TEXT")
    ap.add_argument("--entry", metavar="FILE",
                    help="print the cone of another program instead of sawc2's")
    ap.add_argument("--rules", action="store_true",
                    help="print every subset rule that fires inside a cone declaration")
    args = ap.parse_args(argv)
    if args.rules:
        _, problems, c = cone()
        for p in problems:
            print(p)
        if problems:
            return 1
        print_rules(c)
        return 0
    if args.entry:
        text, problems, _ = cone(os.path.abspath(args.entry))
        for p in problems:
            print(p)
        sys.stdout.write(text or "")
        return 1 if problems else 0
    if args.why:
        _, problems, c = cone()
        for p in problems:
            print(p)
        if c is None:
            return 1
        for did in sorted(c.reached):
            if args.why in did:
                chain, node = [], did
                while node is not None and node not in chain:
                    chain.append(node)
                    node = c.why.get(node)
                print(" <- ".join(chain))
        return 0
    if args.write or args.instances:
        text, problems, c = cone()
        for p in problems:
            print(p)
        if problems:
            return 1
        if args.instances:
            for did in sorted(c.full_instances):
                d = c.decls[did]
                for inst in sorted(c.full_instances[did]):
                    print("%s %s %s [%s]" % (d["module"], d["kind"], d["name"], ", ".join(inst)))
        if args.write:
            with open(CONE_FILE, "w", encoding="utf-8") as fh:
                fh.write(text)
            print("std cone: wrote %s (%d declarations)"
                  % (os.path.relpath(CONE_FILE, REPO), _declaration_count(text)))
        return 0
    failures, counts = check()
    for f in failures:
        print(f)
    if not failures:
        print("std cone: ok (%d declarations)" % counts["std cone declarations"])
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
