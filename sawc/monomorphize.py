"""design 218 unit 1.5 — MONOMORPHIZATION AS A PRE-CODEGEN PHASE.

Today WHICH generic instantiations exist is decided in three places — the
effect pass, the coroutine transform's promotion walks, and codegen's lazy
`_ensure_monomorphized_*` during lowering — and no judgment with real errors
ever runs on any instance. After this unit there is ONE demand-driven
reachability fixpoint, it runs before the transforms, and codegen only looks
instances up: **codegen lowers, it no longer decides.**

This module is that fixpoint. The spec is `designs/218c-monomorphization-spec.md`
and it is the authority; what follows is the shape, not a restatement.

ROOTS (spec 1b) are every CONCRETE declaration in the compilation unit — entry,
module and std free functions, the methods of non-generic extensions, and
statics' initializers. Spawn and drive sites need no special treatment: they are
call positions inside those bodies. This deliberately over-approximates for a
hosted `-c` object, which keeps every symbol anyway; for an executable the
design-168 reachability strip still decides which BODIES are emitted. Instance
EXISTENCE and body EMISSION stay two different questions and this unit moves
only the first.

THE WALK is reflective over `dataclasses.fields`, the same reach
`substitute_ast_types` has and for the same reason: the checker's own
annotations carry `SawType`s, and an instantiation named only by one of those
is as real as one named by a call. A `SawType` is a LEAF (its `symbol` back-
pointer would drag the whole namespace in), and only dataclasses declared in
`ast_nodes` are entered, so a symbol reached through any other annotation ends
the walk too.

FROM AN INSTANCE the walk continues through the TEMPLATE's body under that
instance's substitution — `Vector<Int>`'s methods demand `VectorIterator<Int>`,
which demands its own field types, to a fixpoint. Stage 1 walks the template
rather than a clone: the demand set is the same either way, and building the
clone is stage 2's business, where the errors it produces become real.

TERMINATION (spec 1d) is the depth limit. A template that demands itself at a
GROWN argument makes the instance graph infinite — `deepen<T>` calling
`deepen<Wrap<T>>` — and the current compiler cannot finish that program
(DF-258b: a 120-second hang when the spec was written, a max-recursion-depth
ICE today, Python's own limit arriving first). Every demand records
`depth = demander's depth + 1`, roots at 0, and a demand past `DEPTH_LIMIT` is
a clean error at the DEMANDING site naming the chain. Per CHAIN, not a global
instance cap, so wide-but-shallow programs are untouched.

SHADOW MODE (stage 1) is how the registry is proved complete before anything
depends on it: the phase runs, codegen is unchanged, and every codegen demand
is checked against the registry on the way past. `SAWC_MONO_SHADOW=strict`
promotes a miss to an internal error, which is how the gate runs it over the
whole corpus. A miss is a demand class this walk failed to enumerate, and it
surfaces on the very first full-suite run rather than as an ICE three stages
later.
"""

import dataclasses
import os
import weakref

from ast_nodes import (
    SawType, TypeKind, EnumInit, FunctionCall, MethodCall,
    StructInit, ext_param_aliases, specialization_key,
)
from errors import ErrorKind
from codegen.mangle import (
    mangle_function, mangle_method, mangle_named, mangle_type,
)
from mono_identity import (
    PRIMITIVE_TYPE_NAMES, IdentityEnv, canonical_enum_args,
    canonical_struct_args, canonicalize_type_kind,
    extension_specialization_key, fill_default_type_args,
)
from type_identity import decl_identity


# Recommended by the spec and ratified with it: deep enough that no legitimate
# chain approaches it (the corpus's deepest is single digits), shallow enough to
# answer fast. Per chain.
DEPTH_LIMIT = 64

# How many hops of a demand chain are rendered before the middle is elided.
_CHAIN_HEAD = 2
_CHAIN_TAIL = 2

# SAWC_MONO_SHADOW — the stage-1 instrument, off by default.
#   (unset)  nothing
#   1        report every shadow MISS and keep compiling (a whole-corpus scan
#            collects the demand classes the walk is missing in one pass)
#   strict   a miss is an internal error — what the gate runs
#   dump     `1`, plus the registry in discovery order
#   trace    `dump`, plus every method-call demand, every extension method
#            walked, and every bounds refusal — the debugging view
_SHADOW = os.environ.get("SAWC_MONO_SHADOW", "")
_TRACE = _SHADOW == "trace"
_DUMP = _SHADOW in ("dump", "trace")

# SAWC_MONO_MEASURE — Amendment A5(b)'s cost model, off by default.
#   splice-all   after the fixpoint, MATERIALIZE every registered instance
#                (copier + the §1c instance check in the template's home module
#                scope) and throw the result away.
#
# It is an instrument and not a mode, and the difference is worth stating
# because the shape looks like the one design 218c's own `citations` lane
# forbids. It judges nothing: it runs against a THROWAWAY reporter of its own
# making, never the compile's, and its answers reach no user and gate no
# program — which is exactly why it can run over a green suite while A3's ~30
# std-instance diagnostics are still owed a ruling. A5(a)'s
# `SAWC_MONO_MATERIALIZE=all`, which reports for real and takes a battery lane,
# is 3c's and is a different thing.
#
# What it exists for: A5(b) rules that the MEASUREMENT decides whether lazy body
# materialization is bought at all, and the number it needs is the per-compile
# cost of materializing everything — which is this, run under §5's own
# instrument (the suite's wall time, 3-run median, uncontended, one machine).
_MEASURE = os.environ.get("SAWC_MONO_MEASURE", "")


@dataclasses.dataclass
class Instance:
    """One registry entry — one (template identity, canonical type arguments).

    `key` IS the mangled symbol, which is the point: one identity, one
    spelling, both sides. `demand` is the FIRST edge the fixpoint recorded, and
    "first" is stable because the walk order is declaration order over roots —
    an irdet obligation, so error attribution cannot reshuffle between runs.
    """
    key: str
    kind: str                    # 'fn' | 'struct' | 'enum' | 'method'
    base: str                    # template identity (design 144), no arguments
    args: list                   # canonical type arguments
    depth: int
    chain: tuple                 # keys from the nearest root, this one last
    demand: tuple                # (source_file, line, column)
    # Method instances only: the receiver instance's mangled name, the method's
    # own name, and the method's own type arguments.
    recv_key: str = None
    method_name: str = None
    method_args: list = None
    # The SOURCE spelling (`deepen<Wrap<Int>>`), for diagnostics. A mangled
    # symbol is the identity and is unreadable at depth — 64 nested `Wrap`s
    # mangle to two thousand characters — so the two are kept apart.
    display: str = ""


class MonoIdentityEnv(IdentityEnv):
    """The phase's view of the declaration tables — see `mono_identity`."""

    def __init__(self, mono):
        # Weak, for the reason `CodegenIdentityEnv` gives: the phase holds the
        # env, so a strong reference here would close a cycle around the whole
        # registry.
        self._m = weakref.proxy(mono)

    def type_params(self, base_name):
        m = self._m
        decl = m.generic_structs.get(base_name) or m.generic_enums.get(base_name)
        return getattr(decl, 'type_params', None) if decl is not None else None

    def is_enum(self, name) -> bool:
        m = self._m
        return name in m.generic_enums or name in m.enum_names

    def is_known_type(self, name) -> bool:
        # Codegen answers from `BUILTIN_TYPE_NAMES | struct_types`, and
        # `struct_types` is keyed by the design-144 identity every declaration
        # in the merged AST carries — which is what `struct_decls` is keyed by
        # here. Enums are excluded on BOTH sides (see DF-286a: the typechecker's
        # third copy does accept them, a latent divergence this unit records
        # rather than resolves).
        m = self._m
        return name in PRIMITIVE_TYPE_NAMES or name in m.struct_decls

    def substitute(self, saw_type):
        # Reached only for a declared DEFAULT being filled in. Codegen
        # substitutes against its live monomorphization context; here the
        # active binding travels with the walk, so the caller has already
        # applied it to the arguments and a default naming an earlier parameter
        # is resolved by `_demand_named_type` before this is asked.
        return saw_type


class Monomorphizer:
    """The demand-driven instance fixpoint (spec phase 2)."""

    def __init__(self, program, namespace, reporter, verbose=False):
        self.program = program
        self.namespace = namespace
        self.reporter = reporter
        self.verbose = verbose

        self.instances: dict = {}
        self.order: list = []
        self.env = MonoIdentityEnv(self)
        self._worklist: list = []
        self._depth_reported: set = set()
        # id(declaration) -> (declaration, descriptor list). The declaration is
        # held so its id cannot be recycled under the cache.
        self._demand_cache: dict = {}
        # The instance whose body is being walked, or None at a root. Read by
        # `_receiver_key` for the bare-receiver recovery below; the worklist is
        # drained one entry at a time, so a single slot is the whole state.
        self._owner = None

        self._build_tables()

    # ---------------------------------------------------------------- tables
    def _build_tables(self):
        """The template registries, built from the MERGED program.

        Mirrors `CodeGenerator.generate`'s own walk deliberately, key for key:
        the two sides must agree about which declarations are templates, and
        the merged AST is the one artifact both of them see. The ordering
        constraint codegen inherits — builtin `Result`, then extensions, then
        the type declarations, then functions — does not bind here, because
        nothing is lowered while the tables are built.
        """
        from ast_nodes import Enum, EnumVariant, TypeParameter

        prog = self.program
        self.generic_functions = {}
        for func in prog.functions:
            if getattr(func, 'type_params', None):
                # Design 105: a generic OVERLOAD carries a distinct `$OL$` base
                # symbol; a lone generic keeps its plain-name key.
                key = getattr(func, 'mangled_symbol', None) or func.name
                self.generic_functions.setdefault(key, func)

        self.generic_structs = {}
        self.struct_decls = {}
        for struct in prog.structs:
            identity = decl_identity(struct)
            self.struct_decls.setdefault(identity, struct)
            if getattr(struct, 'type_params', None):
                self.generic_structs.setdefault(identity, struct)

        self.generic_enums = {}
        self.enum_decls = {}
        self.enum_names = set()
        for enum in prog.enums:
            identity = decl_identity(enum)
            self.enum_decls.setdefault(identity, enum)
            self.enum_names.add(identity)
            if getattr(enum, 'type_params', None):
                self.generic_enums.setdefault(identity, enum)
        # `Result<T, E>` is a typechecker builtin with no declaration in the
        # merged AST; codegen synthesizes the same node in
        # `_register_builtin_enums`, and the identity funnel has to agree that
        # the name denotes an enum with two undefaulted parameters.
        if "Result" not in self.generic_enums:
            self.generic_enums["Result"] = Enum(
                name="Result",
                variants=[
                    EnumVariant(name="Ok", associated_types=[
                        ("value", SawType(TypeKind.TYPE_PARAM, type_param_name="T"))]),
                    EnumVariant(name="Err", associated_types=[
                        ("error", SawType(TypeKind.TYPE_PARAM, type_param_name="E"))]),
                ],
                type_params=[TypeParameter(name="T", line=0, column=0),
                             TypeParameter(name="E", line=0, column=0)],
                line=0, column=0)
            self.enum_names.add("Result")

        self.generic_extensions = {}
        self.specialized_extensions = {}
        self.plain_generic_methods = {}
        struct_params = {decl_identity(s): getattr(s, 'type_params', None) or []
                         for s in prog.structs}
        struct_params.update({decl_identity(e): getattr(e, 'type_params', None) or []
                              for e in prog.enums})
        for ext in prog.extensions:
            name = ext.struct_name
            # DF-286a: from the extension's declared PARAMETERS, through the
            # shared funnel — `Extension.type_args` is empty on every extension
            # the parser produces, so keying on it called `extension
            # Vector<String>` generic and walked `join` onto every `Vector<T>`.
            key = extension_specialization_key(self.env, ext)
            if key:
                # Pad with the type's trailing defaults so a specialization
                # written at the short spelling still matches the filled
                # identity (codegen's `_pad_spec_key_with_defaults`).
                params = struct_params.get(name) or []
                if len(key) < len(params):
                    padded = list(key)
                    for i in range(len(key), len(params)):
                        default = getattr(params[i], 'default', None)
                        if default is None:
                            break
                        padded.extend(specialization_key([default]) or ("",))
                    key = tuple(padded)
                self.specialized_extensions.setdefault((name, key), []).append(ext)
            elif getattr(ext, 'type_params', None):
                self.generic_extensions.setdefault(name, []).append(ext)
            else:
                for m in ext.methods:
                    if getattr(m, 'type_params', None) and not m.is_init:
                        self.plain_generic_methods.setdefault(
                            name, {}).setdefault(m.name, m)

    # ------------------------------------------------------------- the phase
    def run(self):
        """Walk the roots, then the instances they demand, to a fixpoint."""
        for root, site in self._roots():
            self._walk(root, {}, depth=0, chain=(), site=site)
        while self._worklist:
            self._process(self._worklist.pop(0))
        if self.verbose:
            print(f"    Monomorphization: {len(self.order)} instance(s) "
                  f"discovered")
        if _DUMP:
            # The registry, in discovery order — which is the order the spec's
            # attribution rule calls "first", so a dump is also the evidence
            # that the walk is deterministic.
            for key in self.order:
                inst = self.instances[key]
                print(f"  mono[{inst.kind}] d{inst.depth} {key}")
        return self

    def _roots(self):
        """Every concrete declaration, in declaration order.

        Order is what makes first-demand attribution deterministic, so it is
        the program's own and never a set's.
        """
        prog = self.program
        for func in prog.functions:
            if not getattr(func, 'type_params', None):
                yield func, _site(func)
        for ext in prog.extensions:
            # A specialized extension head is also spelled with type PARAMETERS
            # (DF-286a), so this one test covers both: generic and specialized
            # alike are reached through their receiver's instances, never as
            # roots.
            if getattr(ext, 'type_params', None):
                continue
            for m in ext.methods:
                if getattr(m, 'type_params', None):
                    continue      # method-generic: reached through its calls
                yield m, _site(m)
        for static in getattr(prog, 'statics', []):
            yield static, _site(static)
        for sa in getattr(prog, 'static_asserts', []):
            yield sa, _site(sa)

    # -------------------------------------------------------------- the walk
    def _walk(self, node, subst, depth, chain, site):
        """Every demand one declaration's subtree can make, under `subst`.

        The subtree is walked ONCE PER COMPILE and its demands are kept as
        descriptors (`_collect`); an instance then only applies its own binding
        to that list. The distinction is the whole cost model: `Vector`'s
        methods are walked once, not once for each of the dozens of `Vector<T>`
        instantiations a program has — which is a factor of the instance count
        on a corpus where std's containers dominate.
        """
        for kind, payload, where in self._demands_of(node):
            where = where or site
            if kind == 'type':
                self._demand_type(payload, subst, depth, chain, where)
            elif kind == 'fn':
                name, targs = payload
                self._demand_function(name, targs, subst, depth, chain, where)
            elif kind == 'named':
                base, targs = payload
                self._demand_named(base, targs, subst, depth, chain, where)
            elif kind == 'method':
                self._method_call_demands(payload, subst, depth, chain, where)

    def _demands_of(self, node):
        """The cached descriptor list for one declaration, collected on first
        ask. Keyed by object identity, with the node held so the id stays its
        own."""
        entry = self._demand_cache.get(id(node))
        if entry is None:
            entry = (node, self._collect(node))
            self._demand_cache[id(node)] = entry
        return entry[1]

    def _collect(self, node):
        """The reflective walk, ONE declaration, subst-free.

        The same reach `substitute_ast_types` has, and for the same reason: the
        checker's own annotations carry `SawType`s. A `SawType` is a LEAF (its
        `symbol` back-pointer would drag the whole namespace in) and only
        dataclasses declared in `ast_nodes` are entered, so a symbol reached
        through any other annotation ends the walk too.
        """
        out = []
        seen_types = set()
        stack = [node]
        seen = set()
        while stack:
            n = stack.pop()
            if n is None:
                continue
            if isinstance(n, SawType):
                if self._names_a_generic(n):
                    tag = repr(n)
                    if tag not in seen_types:
                        seen_types.add(tag)
                        out.append(('type', n, None))
                continue
            if isinstance(n, (list, tuple)):
                stack.extend(n)
                continue
            if isinstance(n, (str, int, float, bool, type)) or n is None:
                continue
            names = _walkable_fields(type(n))
            if names is None:
                continue
            if id(n) in seen:
                continue
            seen.add(id(n))
            self._collect_node(n, out)
            for name in names:
                v = getattr(n, name)
                # Most fields of an AST node are a name, a line, a column or a
                # flag. Dropping them at the PUSH saves a push, a pop and the
                # isinstance ladder above for the majority of the traversal.
                if v is None or type(v) in _SCALAR_FIELDS:
                    continue
                stack.append(v)
        return out

    def _collect_node(self, node, out):
        """The CALL-shaped demands: the ones a type walk cannot see.

        Four node classes carry resolved type arguments after checking, and one
        of them means four different things (the census's sharpest trap):
        `MethodCall` is the instance-method call, the module-qualified free
        function call, the static-method call and the qualified enum
        construction, told apart by the stamps the checker leaves.
        """
        where = _site(node)
        if isinstance(node, FunctionCall):
            targs = getattr(node, 'type_args', None)
            if targs:
                name = self._function_template_name(node)
                if name is not None:
                    out.append(('fn', (name, list(targs)), where))
            return
        if isinstance(node, MethodCall):
            out.append(('method', node, where))
            return
        if isinstance(node, (StructInit, EnumInit)):
            targs = getattr(node, 'type_args', None)
            base = (getattr(node, 'struct_name', None)
                    or getattr(node, 'enum_name', None))
            if base in self.generic_structs or base in self.generic_enums:
                out.append(('named', (base, list(targs or [])), where))
            return

    def _names_a_generic(self, t, depth=0):
        """Whether a type could possibly demand an instance.

        The pruning that makes collection worth caching: most types in a body
        are primitives, and carrying them into every instance's application
        pass would put the cost straight back.
        """
        if t is None or not isinstance(t, SawType) or depth > 12:
            return False
        kind = t.kind
        if kind == TypeKind.STRUCT and t.struct_name:
            if (t.struct_name in self.generic_structs
                    or t.struct_name in self.generic_enums):
                return True
        elif kind == TypeKind.ENUM and t.enum_name:
            if (t.enum_name in self.generic_enums
                    or t.enum_name in self.generic_structs):
                return True
        for child in (t.inner_type, t.array_element_type, t.func_return_type):
            if self._names_a_generic(child, depth + 1):
                return True
        for group in (t.type_args, t.element_types, t.param_types):
            for child in (group or ()):
                if self._names_a_generic(child, depth + 1):
                    return True
        return False

    def _function_template_name(self, node):
        """Which generic free-function template a call names.

        `resolved_symbol` wins where it names one, because design 105 gives a
        generic OVERLOAD a distinct `$OL$` base and the plain name would pick
        the wrong member — the same choice `_generate_function_call` makes.
        """
        sym = getattr(node, 'resolved_symbol', None)
        if sym and sym in self.generic_functions:
            return sym
        name = getattr(node, 'name', None)
        if name and name in self.generic_functions:
            return name
        return None

    def _method_call_demands(self, node, subst, depth, chain, where):
        targs = getattr(node, 'type_args', None)
        # (a) The module-qualified FREE function call, which the checker parses
        #     as a member access and stamps like a `FunctionCall`.
        if targs:
            sym = getattr(node, 'resolved_symbol', None)
            name = getattr(node, 'method_name', None)
            for candidate in (sym, name):
                if candidate and candidate in self.generic_functions:
                    self._demand_function(candidate, targs, subst, depth, chain,
                                          where)
                    return
        # (b) The receiver's own instantiation, then the method-generic
        #     instance on top of it. A static call carries the receiver on an
        #     `Identifier`; an instance call on the object's resolved type.
        recv = self._receiver_type(node)
        if recv is None:
            return
        recv = _apply(recv, subst)
        self._demand_type(recv, {}, depth, chain, where)
        if not targs:
            return
        method_name = getattr(node, 'method_name', None)
        if not method_name:
            return
        recv_key = self._receiver_key(recv, depth, chain, where)
        if _TRACE:
            print(f"  mono[mcall] {method_name} recv={recv} key={recv_key} "
                  f"targs={targs}")
        if recv_key is None:
            return
        self._demand_method(recv, recv_key, method_name, targs, subst, depth,
                            chain, where)

    def _receiver_type(self, node):
        # An `Arc<T>` / `Box<T>` receiver FORWARDS to the payload's own method
        # (census M2), so the instance demanded is `T`'s, not the wrapper's.
        # The checker stamps the payload type for exactly this reason.
        forward = (getattr(node, 'arc_forward_payload_type', None)
                   or getattr(node, 'box_forward_payload_type', None))
        if forward is not None:
            return forward
        if getattr(node, 'is_static_method_call', False):
            base = getattr(node, 'static_receiver', None)
            obj = getattr(node, 'object', None)
            args = getattr(obj, 'type_args', None) if obj is not None else None
            if not base:
                return None
            return SawType(TypeKind.STRUCT, struct_name=base,
                           type_args=list(args) if args else None)
        obj = getattr(node, 'object', None)
        if obj is None:
            return None
        return getattr(obj, 'resolved_type', None)

    def _receiver_key(self, recv, depth, chain, site):
        """The name a method symbol mangles AGAINST.

        A generic receiver contributes its own instance's mangled name; a plain
        one contributes its identity unchanged, and design 40 item 9's
        primitive receivers (a method-generic on `extension String`) contribute
        the mangler's own spelling. This is exactly what
        `_generate_method_call` passes as `struct_name`, which is what makes
        the two symbols the same string.
        """
        if recv is None or not isinstance(recv, SawType):
            return None
        if recv.kind == TypeKind.STRUCT and recv.struct_name:
            name = recv.struct_name
        elif recv.kind == TypeKind.ENUM and recv.enum_name:
            name = recv.enum_name
        else:
            try:
                return mangle_type(recv)
            except Exception:
                return None
        if name in self.generic_structs or name in self.generic_enums:
            if not recv.type_args:
                # THE BARE RECEIVER (design 146 unit C). `self` inside an
                # already-instantiated body is recorded as a bare `Vector`,
                # leaving the struct's own parameters unbound — so the
                # instantiation cannot be read off the type and has to come
                # from the body being walked, which is the instance that owns
                # it. Codegen recovers the same answer from `mono_struct_args`,
                # keyed by the mangled name it is generating into.
                owner = self._owner
                if owner is not None and owner.base == name:
                    return owner.recv_key or owner.key
                return None
            # A generic receiver whose arguments are still abstract demands
            # nothing — the enclosing template is being walked without a
            # binding, and the concrete call will be reached through the
            # instance that supplies one.
            return self._demand_named(name, list(recv.type_args or []), {},
                                      depth, chain, site)
        return name

    # ------------------------------------------------------------- demanding
    def _demand_type(self, saw_type, subst, depth, chain, site):
        """Every named generic a type NAMES, to any nesting depth.

        Returns the mangled key of the OUTERMOST instance, or None — the method
        path needs it to compose a receiver-qualified method symbol.
        """
        t = _apply(saw_type, subst)
        return self._demand_type_closure(t, depth, chain, site)

    def _demand_type_closure(self, t, depth, chain, site):
        if t is None or not isinstance(t, SawType):
            return None
        kind = t.kind
        if kind in (TypeKind.STRUCT, TypeKind.ENUM):
            # The named arm hands the WHOLE type to `_demand_named`, arguments
            # included, and does NOT descend first. Descending here and then
            # letting `_demand_named` descend again over the same arguments is
            # 2^depth work on a chain like `Wrap<Wrap<…>>` — which the
            # depth-limit test builds sixty-four deep, so the compile stopped
            # answering and took a suite worker with it. One descent, behind
            # the cache check, is O(depth).
            name = t.struct_name if kind == TypeKind.STRUCT else t.enum_name
            if name:
                return self._demand_named(name, list(t.type_args or []), {},
                                          depth, chain, site)
            return None
        for child in (t.inner_type, t.array_element_type, t.func_return_type):
            self._demand_type_closure(child, depth, chain, site)
        for group in (t.element_types, t.param_types):
            for child in (group or ()):
                self._demand_type_closure(child, depth, chain, site)
        return None

    def _demand_named(self, base, raw_args, subst, depth, chain, site):
        """A named struct/enum instantiation, through the identity funnel."""
        if base not in self.generic_structs and base not in self.generic_enums:
            return None
        args = [_apply(a, subst) for a in raw_args]
        if self.env.is_enum(base):
            args = canonical_enum_args(self.env, base, args)
            kind = 'enum'
        else:
            args = canonical_struct_args(self.env, base, args)
            kind = 'struct'
        if not args or any(_is_abstract(a) for a in args):
            return None
        key = mangle_named(base, args)
        if key in self.instances:
            return key                     # its argument closure is already done
        self._register(key, kind, base, args, depth, chain, site)
        if key not in self.instances:
            return None                    # refused by the depth limit
        # The arguments' OWN instances, AFTER this one is in the cache: a
        # `Foo<Vector<Int>>` demands `Vector<Int>`, and that is what lets the
        # collection pass prune a bare `T` from a template body — whatever `T`
        # turns out to be was already demanded by whoever supplied it. Ordered
        # after the registration so a self-referential argument cannot loop.
        for a in args:
            self._demand_type_closure(a, depth, chain, site)
        return key

    def _demand_function(self, name, raw_args, subst, depth, chain, site):
        # NOT canonicalized. `_instantiate_generic_function` mangles the
        # SUBSTITUTED arguments and nothing else — the identity funnel's three
        # rules are the NAMED-TYPE rules, and a free function's arguments never
        # pass through them. Matching that exactly is the point: the registry
        # key has to be the string codegen computes, or stage 3's lookup misses
        # a real instance.
        args = [_apply(a, subst) for a in raw_args]
        if any(_is_abstract(a) for a in args):
            return None
        for a in args:
            self._demand_type_closure(a, depth, chain, site)
        return self._register(mangle_function(name, args), 'fn', name, args,
                              depth, chain, site)

    def _demand_method(self, recv_type, recv_key, method_name, raw_args, subst,
                       depth, chain, site):
        # Method-level type arguments are NOT canonicalized either, for the
        # same reason and with one consequence worth recording: a `Slot<T>`
        # whose RECEIVER carries the arity-1 erased box (`Box<any Error>`,
        # normalized by the funnel at the type position) takes an arity-2
        # `Box<any Error, GlobalAllocator>` in its method symbol, because
        # `_generate_method_call` substitutes and mangles without asking the
        # funnel. That asymmetry is codegen's today; the registry mirrors it
        # rather than correcting it, since a registry that disagreed would miss
        # the instance that actually exists.
        margs = [_apply(a, subst) for a in raw_args]
        if any(_is_abstract(a) for a in margs):
            return None
        for a in margs:
            self._demand_type_closure(a, depth, chain, site)
        base = recv_type.struct_name or recv_type.enum_name or recv_key
        recv_inst = self.instances.get(recv_key)
        struct_args = (recv_inst.args if recv_inst is not None
                       else list(recv_type.type_args or []))
        key = mangle_method(recv_key, method_name, method_type_args=margs)
        inst = self._register(key, 'method', base, struct_args, depth, chain,
                              site)
        if inst is not None:
            inst.recv_key = recv_key
            inst.method_name = method_name
            inst.method_args = margs
        return inst

    def _register(self, key, kind, base, args, depth, chain, site):
        """Enter an instance, once. Later demands hit the cache, which is what
        makes one bad instance one report however many paths reach it."""
        existing = self.instances.get(key)
        if existing is not None:
            return existing
        display = _display(base, args)
        if depth + 1 > DEPTH_LIMIT:
            self._report_depth(display, chain, site)
            return None
        inst = Instance(key=key, kind=kind, base=base, args=list(args),
                        depth=depth + 1, chain=chain + (key,), demand=site,
                        display=display)
        self.instances[key] = inst
        self.order.append(key)
        self._worklist.append(inst)
        return inst

    def _report_depth(self, display, chain, site):
        """DF-258b's refusal. One per chain root, so a runaway template does
        not print sixty-four near-identical lines.

        Rendered in SOURCE spelling and elided in the middle, because the thing
        being described is a chain sixty-five instantiations long and the
        reader needs its two ends and its shape, not its every link.
        """
        anchor = chain[0] if chain else display
        if anchor in self._depth_reported:
            return
        self._depth_reported.add(anchor)
        src, line, column = site if site else (None, 1, 1)
        hops = [self.instances[k].display if k in self.instances else k
                for k in chain] + [display]
        self.reporter.error(
            ErrorKind.TYPE_MISMATCH,
            f"instantiation of `{display}` exceeds the instantiation depth "
            f"limit ({DEPTH_LIMIT}): {_render_chain(hops)}",
            line, column,
            hint="a generic that instantiates ITSELF at a bigger type argument "
                 "has no finite instance set — break the recursion by taking "
                 "the growing part behind a `Box`, or by making the recursive "
                 "call non-generic",
            source_file=src)

    # ------------------------------------------------------- instance bodies
    def _process(self, inst):
        """Continue the walk THROUGH an instance, under its own binding."""
        self._owner = inst
        try:
            self._process_inner(inst)
        finally:
            self._owner = None

    def _process_inner(self, inst):
        if inst.kind == 'fn':
            template = self.generic_functions.get(inst.base)
            if template is None:
                return
            subst = _zip_params(getattr(template, 'type_params', None), inst.args)
            self._walk(template, subst, inst.depth, inst.chain, inst.demand)
            return
        if inst.kind in ('struct', 'enum'):
            self._process_type(inst)
            return
        if inst.kind == 'method':
            self._process_method(inst)

    def _process_type(self, inst):
        decl = (self.generic_structs.get(inst.base)
                or self.generic_enums.get(inst.base))
        if decl is None:
            return
        subst = _zip_params(getattr(decl, 'type_params', None), inst.args)
        # The TYPE CLOSURE: an instantiated struct's substituted FIELD types
        # (and an enum's payload types) are demands. This is what subsumes
        # DF-256a's template reach-through — the registry has already closed
        # over them by the time registration order is computed.
        for field in getattr(decl, 'fields', None) or ():
            self._demand_type(field.type, subst, inst.depth, inst.chain,
                              inst.demand)
        for variant in getattr(decl, 'variants', None) or ():
            for _pname, ptype in variant.associated_types:
                self._demand_type(ptype, subst, inst.depth, inst.chain,
                                  inst.demand)
        # …and the extension methods that exist for THIS instantiation, decided
        # by the same three rules codegen's `_monomorphize_extension` applies:
        # the conditional-conformance bounds filter, the specialized-extension
        # override, and the method-generic skip (their own type arguments are
        # only known at a call site).
        for ext, skip in self._applicable_extensions(inst.base, inst.args):
            aliases = ext_param_aliases(
                getattr(ext, 'type_params', None),
                getattr(decl, 'type_params', None) or [])
            ext_subst = dict(subst)
            for declared_name, alias in aliases:
                if declared_name in subst:
                    ext_subst[alias] = subst[declared_name]
            for m in ext.methods:
                if m.name in skip or getattr(m, 'type_params', None):
                    continue
                if _TRACE:
                    print(f"  mono[walk] {inst.key}.{m.name}")
                self._walk(m, ext_subst, inst.depth, inst.chain, inst.demand)

    def _applicable_extensions(self, base, args):
        """(extension, skipped-method-names) for one type instantiation."""
        spec_key = specialization_key(args)
        full_key = (base, spec_key)
        overridden = set()
        for ext in self.specialized_extensions.get(full_key, ()):
            for m in ext.methods:
                overridden.add(m.name)
        out = []
        for ext in self.generic_extensions.get(base, ()):
            if not self._bounds_satisfied(ext, args):
                continue
            out.append((ext, overridden))
        for ext in self.specialized_extensions.get(full_key, ()):
            out.append((ext, set()))
        return out

    def _bounds_satisfied(self, ext, args):
        """Design 14's conditional conformance, answered by the SHARED
        namespace helper so the phase and the checker cannot disagree."""
        for i, tp in enumerate(getattr(ext, 'type_params', None) or []):
            if not tp.bounds or i >= len(args):
                continue
            for bound in tp.bounds:
                if not self.namespace.type_satisfies_bound(args[i], bound):
                    if _TRACE:
                        print(f"  mono[bounds] {ext.struct_name}: "
                              f"{args[i]} does not satisfy {bound}")
                    return False
        return True

    def _process_method(self, inst):
        """A method-generic instance: the struct's binding plus the method's.

        The template search is `_ensure_monomorphized_generic_method`'s, in the
        same order: the receiver's generic extensions first, then design 40
        item 9's `plain_generic_methods` (a generic method on a NON-generic
        type's extension, whose receiver contributes no binding at all).
        """
        decl = (self.generic_structs.get(inst.base)
                or self.generic_enums.get(inst.base))
        subst = _zip_params(getattr(decl, 'type_params', None) if decl else None,
                            inst.args)
        method = None
        owning = None
        for ext in self.generic_extensions.get(inst.base, ()):
            for m in ext.methods:
                if m.name == inst.method_name and getattr(m, 'type_params', None):
                    method, owning = m, ext
                    break
            if method is not None:
                break
        if method is None:
            method = (self.plain_generic_methods.get(inst.base, {})
                      .get(inst.method_name)
                      or self.plain_generic_methods.get(inst.recv_key, {})
                      .get(inst.method_name))
        if method is None:
            return
        # DF-216h: the extension may RENAME the parameters it re-declares, and
        # the method's body is written in ITS names.
        if owning is not None and decl is not None:
            for declared_name, alias in ext_param_aliases(
                    getattr(owning, 'type_params', None),
                    getattr(decl, 'type_params', None) or []):
                if declared_name in subst:
                    subst[alias] = subst[declared_name]
        subst.update(_zip_params(getattr(method, 'type_params', None),
                                 inst.method_args or []))
        self._walk(method, subst, inst.depth, inst.chain, inst.demand)

    # -------------------------------------------------------- shadow mode
    def shadow(self, key, what, demander):
        """Codegen asked for `key`. Stage 1's completeness proof.

        A miss is a demand class this walk failed to enumerate. Logged by
        default so a full-suite run collects the whole list in one pass;
        `SAWC_MONO_SHADOW=strict` promotes it to an internal error, which is
        what the gate runs, and is the shape stage 3's ICE-on-miss takes.
        """
        if key in self.instances:
            return
        message = (f"monomorphization shadow MISS: {what} `{key}` was not "
                   f"discovered by the fixpoint (demanded while lowering "
                   f"{demander})")
        if _SHADOW == "strict":
            raise AssertionError(message)
        if _SHADOW:
            print(f"  {message}")


# Field values that can never lead to a demand, filtered where they are read.
_SCALAR_FIELDS = frozenset((str, int, bool, float, bytes))


# class -> the field NAMES the collection walk descends through, or None for a
# class it must not enter. `dataclasses.fields()` rebuilds a tuple of Field
# objects on every call, and the walk asks once per node over tens of thousands
# of nodes; the answer is a property of the CLASS, so it is asked once.
_WALKABLE_FIELDS: dict = {}


def _walkable_fields(cls):
    names = _WALKABLE_FIELDS.get(cls)
    if names is None:
        if (not dataclasses.is_dataclass(cls)
                or cls.__module__ != 'ast_nodes'):
            # A symbol or another non-AST dataclass reached through an
            # annotation. Entering one would walk the namespace.
            _WALKABLE_FIELDS[cls] = False
            return None
        names = tuple(f.name for f in dataclasses.fields(cls))
        _WALKABLE_FIELDS[cls] = names
    elif names is False:
        return None
    return names


def _zip_params(params, args):
    return {tp.name: arg for tp, arg in zip(params or [], args or [])}


def const_bindings(type_params, args, aliases=()):
    """This instance's const VALUE parameters — DF-286c face 1's input.

    NAME -> (declared const type, the bound `CONST_VALUE` argument), for every
    `<const N: Int>` among `type_params`. Stamped on the clone as
    `mono_const_bindings` (see `ast_nodes.Function`), because a clone has no
    type parameters left and a const parameter is a VALUE in the body, which no
    amount of substituting `SawType`s reaches.

    `aliases` is `ext_param_aliases`' answer: an extension may RE-DECLARE the
    type's parameters under its own names (DF-216h), and a method body is
    written in the extension's names, so the binding is recorded under both.
    """
    out = {}
    for tp, arg in zip(type_params or (), args or ()):
        if getattr(tp, 'is_const', False) and arg is not None:
            out[tp.name] = (tp.const_type, arg)
    for declared_name, alias in aliases or ():
        if declared_name in out:
            out[alias] = out[declared_name]
    return out


def substituted_param_names(template, type_map):
    """The by-value parameters of `template` whose declared type NAMES one of
    `type_map`'s parameters — §1c skip 4's input.

    Computed HERE, at the clone, because it is the last place both artifacts
    exist: the substituted clone has no type parameters left to read the answer
    off. A REFERENCE parameter is excluded — a borrow is not a transfer, so it
    never reaches the checkpoint the skip guards — and so is `self`.
    """
    names = set()
    keys = set(type_map or ())
    if not keys:
        return frozenset()
    for p in getattr(template, 'parameters', None) or ():
        name = getattr(p, 'name', None)
        t = getattr(p, 'type', None)
        if not name or name == 'self' or t is None:
            continue
        if t.kind == TypeKind.REFERENCE:
            continue
        if _type_names_param(t, keys):
            names.add(name)
    return frozenset(names)


def _type_names_param(t, keys, depth=0):
    """Whether `t` spells one of `keys` anywhere — the same reach
    `SawType.substitute` has, which is what makes the answer agree with it."""
    if t is None or not isinstance(t, SawType) or depth > 12:
        return False
    if t.kind == TypeKind.TYPE_PARAM and t.type_param_name in keys:
        return True
    # design 37: a bare type parameter also arrives STRUCT-kinded, spelled by
    # name, which is the shape `Vector<T>.push(value: T)` actually parses to.
    if t.kind == TypeKind.STRUCT and t.struct_name in keys:
        return True
    for child in (t.inner_type, t.array_element_type, t.func_return_type):
        if _type_names_param(child, keys, depth + 1):
            return True
    for group in (t.type_args, t.element_types, t.param_types):
        for child in (group or ()):
            if _type_names_param(child, keys, depth + 1):
                return True
    return False


def _apply(saw_type, subst):
    if saw_type is None or not subst or not isinstance(saw_type, SawType):
        return saw_type
    return saw_type.substitute(subst)


def _is_abstract(t):
    """Whether a type still names a parameter — a template walked with a
    partial binding, which demands nothing until the binding is complete."""
    if t is None or not isinstance(t, SawType):
        return True
    if t.kind == TypeKind.TYPE_PARAM:
        return True
    if t.kind == TypeKind.SELF:
        return True
    for child in (t.inner_type, t.array_element_type, t.func_return_type):
        if child is not None and _is_abstract(child):
            return True
    for group in (t.type_args, t.element_types, t.param_types):
        for child in (group or ()):
            if _is_abstract(child):
                return True
    return False


def _site(node):
    src = getattr(node, 'source_file', None)
    line = getattr(node, 'line', 0) or 1
    column = getattr(node, 'column', 0) or 1
    return (src, line, column)


# How deeply a type argument is spelled out before the rest becomes `…`. Two
# levels is enough to SHOW the growth (`Wrap<Wrap<…>>`) without printing it.
_DISPLAY_DEPTH = 2


def _display(base, args):
    """One instance in source spelling, elided past `_DISPLAY_DEPTH`."""
    short = base.split('$m$')[0]
    if not args:
        return short
    return f"{short}<{', '.join(_type_display(a) for a in args)}>"


def _type_display(t, level=0):
    if t is None or not isinstance(t, SawType):
        return "?"
    args = t.type_args
    if not args:
        return str(t).split('$m$')[0]
    name = (t.struct_name or t.enum_name or "?").split('$m$')[0]
    if level >= _DISPLAY_DEPTH:
        return f"{name}<…>"
    inner = ', '.join(_type_display(a, level + 1) for a in args)
    return f"{name}<{inner}>"


def _render_chain(hops):
    if len(hops) <= _CHAIN_HEAD + _CHAIN_TAIL:
        return " → ".join(hops)
    return " → ".join(list(hops[:_CHAIN_HEAD]) + ["…"]
                      + list(hops[-_CHAIN_TAIL:]))


# --------------------------------------------------------------------------
# THE MATERIALIZATION FUNNEL (obligation 1).
#
# One instance, every body it owns: clone the pristine template through the
# copier under this instance's binding, and run the §1c instance check on the
# clone through `_instance_check_scope`. Three registry kinds, three template
# stores, ONE funnel — because the two things that must never disagree about
# what a materialized body IS are the instrument that measures the check and
# the cutover that ships it.
#
# ENTRY POINTS:
#   * `measure_splice_all` — A5(b)'s cost model / the §5 instrument, which
#     throws the result away against a reporter of its own making.
#   * the splice-all census (`.build/scratch/census_splice/census_lib.py`),
#     which drives the same funnel with a per-body reporter so it can record
#     every diagnostic rather than only the first of a compile.
#
# A `hook` sees each (instance, body) pair: `before(...)` runs ahead of the
# check (the census installs its reporter there) and `after(...)` behind it.
# --------------------------------------------------------------------------

def materialize_instance(mono, tc, inst, hook=None):
    """Materialize + instance-check every body `inst` owns. The one funnel."""
    from mono_copy import substituting_copy
    # A CONFORMANCE IS A PROGRAM-WIDE FACT (Amendment B1), and the substitution
    # MAP is built from one: `_add_associated_type_bindings` reads
    # `namespace.conformances` to bind `Item -> String` for a `<T: Container>`
    # instance. Building the map under the ambient namespace is DF-286c face 2 —
    # the lookup found nothing, `Item` stayed unbound, and the clone's signature
    # said `-> Item` while its body returned `String`. The check itself installs
    # the same namespace through `_instance_check_scope`; this is the half that
    # runs BEFORE the clone exists.
    saved = tc.namespace
    tc.namespace = mono.namespace
    try:
        if inst.kind in ("struct", "enum"):
            _materialize_type_instance(mono, tc, inst, substituting_copy, hook)
        elif inst.kind == "fn":
            _materialize_fn_instance(mono, tc, inst, substituting_copy, hook)
        elif inst.kind == "method":
            _materialize_method_instance(mono, tc, inst, substituting_copy, hook)
    finally:
        tc.namespace = saved


def _run_body(tc, mono, inst, template, clone, type_map, display, method_name,
              flavor, check, hook):
    # §1c skip 4 reads the TEMPLATE: the question is which by-value parameters
    # were declared at a type PARAMETER, and the clone has none left to read.
    substituted = substituted_param_names(template, type_map)
    if hook is not None:
        hook.before(inst, method_name, flavor)
    with tc._checking_instance(display, substituted_params=substituted):
        with tc._instance_check_scope(clone, type_map, mono.namespace):
            check()
    if hook is not None:
        hook.after(inst, method_name, flavor, clone)


def _materialize_type_instance(mono, tc, inst, copier, hook):
    decl = (mono.generic_structs.get(inst.base)
            or mono.generic_enums.get(inst.base))
    if decl is None:
        return
    struct_tps = getattr(decl, 'type_params', None) or []
    base_map = _zip_params(struct_tps, inst.args)
    for ext, skip in mono._applicable_extensions(inst.base, inst.args):
        aliases = ext_param_aliases(getattr(ext, 'type_params', None),
                                    struct_tps)
        for m in ext.methods:
            if m.name in skip or getattr(m, 'type_params', None):
                continue
            entry = tc.pristine_generic_struct_method(ext.struct_name, m.name)
            if entry is None or entry[1] is not ext:
                # The design-70 store is keyed by (struct, method) alone, so
                # two extensions on one type that declare the same name
                # collide; take the snapshot only when it is THIS one's.
                continue
            type_map = dict(base_map)
            for declared, alias in aliases:
                if declared in base_map:
                    type_map[alias] = base_map[declared]
            tc._add_associated_type_bindings(type_map, struct_tps, inst.args)
            clone = copier(entry[0], type_map)
            clone.type_params = []
            clone.is_mono_instance = True
            clone.mono_const_bindings = const_bindings(struct_tps, inst.args,
                                                       aliases)
            _run_body(tc, mono, inst, entry[0], clone, type_map,
                      f"{inst.display}.{m.name}", m.name, "type-method",
                      lambda ext=ext, clone=clone, type_map=type_map:
                          tc._check_method(ext.struct_name, clone, type_map),
                      hook)


def _materialize_fn_instance(mono, tc, inst, copier, hook):
    pristine = tc.pristine_generic(inst.base)
    if pristine is None:
        if hook is not None:
            hook.no_template(inst, "fn")
        return
    tps = getattr(pristine, 'type_params', None) or []
    type_map = _zip_params(tps, inst.args)
    tc._add_associated_type_bindings(type_map, tps, inst.args)
    clone = copier(pristine, type_map)
    clone.name = inst.key
    clone.type_params = []
    clone.mangled_symbol = None
    clone.is_mono_instance = True
    clone.mono_const_bindings = const_bindings(tps, inst.args)
    _run_body(tc, mono, inst, pristine, clone, type_map, inst.display, None,
              "fn", lambda: tc._check_function(clone), hook)


def _materialize_method_instance(mono, tc, inst, copier, hook):
    """A method-GENERIC instance (`Dual<T>.mix<U>`), registry kind 'method'.

    Two flavors, in `_process_method`'s own order: the method-generic on a
    GENERIC struct's extension (design 74 shape 2's store) first, then design 40
    item 9's method-generic on a NON-generic type's extension.
    """
    name = inst.method_name
    entry = tc.pristine_generic_struct_method(inst.base, name)
    if entry is not None:
        pristine, ext = entry
        struct_tps = getattr(ext, 'type_params', None) or []
        method_tps = getattr(pristine, 'type_params', None) or []
        type_map = _zip_params(struct_tps, inst.args)
        type_map.update(_zip_params(method_tps, inst.method_args or []))
        tc._add_associated_type_bindings(type_map, struct_tps, inst.args)
        tc._add_associated_type_bindings(type_map, method_tps,
                                         inst.method_args or [])
        clone = copier(pristine, type_map)
        clone.name = inst.key
        clone.type_params = []
        clone.is_mono_instance = True
        bindings = const_bindings(struct_tps, inst.args)
        bindings.update(const_bindings(method_tps, inst.method_args or []))
        clone.mono_const_bindings = bindings
        _run_body(tc, mono, inst, pristine, clone, type_map,
                  f"{inst.display}.{name}", name,
                  "method-generic-on-generic-struct",
                  lambda: tc._check_method(inst.base, clone, type_map), hook)
        return
    entry = (tc.pristine_generic_method(inst.base, name)
             or tc.pristine_generic_method(inst.recv_key, name))
    if entry is None:
        if hook is not None:
            hook.no_template(inst, "method")
        return
    pristine, _ext = entry
    method_tps = getattr(pristine, 'type_params', None) or []
    type_map = _zip_params(method_tps, inst.method_args or [])
    tc._add_associated_type_bindings(type_map, method_tps,
                                     inst.method_args or [])
    clone = copier(pristine, type_map)
    clone.name = inst.key
    clone.type_params = []
    clone.is_mono_instance = True
    clone.mono_const_bindings = const_bindings(method_tps,
                                               inst.method_args or [])
    _run_body(tc, mono, inst, pristine, clone, type_map,
              f"{inst.display}.{name}", name,
              "method-generic-on-plain-extension",
              lambda: tc._check_method(inst.base, clone, {}), hook)


def measure_splice_all(mono, typechecker):
    """A5(b)'s cost model: materialize EVERY registered instance, then discard.

    Stage 3c's per-compile work, done here so its price can be read off §5's own
    instrument before the shape of 3c is chosen: for each registered instance,
    clone its template through the copier under the instance's binding and run
    the §1c check on the clone in the template's home module scope. Both halves
    matter — the clone is A2(a)'s cost and the check is §1c's — and neither is
    guessable from the other.

    Nothing is spliced and nothing is reported: a throwaway reporter of this
    function's own making stands in for the compile's for the duration, so the
    ~30 std-instance diagnostics A3 still owes a ruling on cannot reach a user
    or a gate. See `_MEASURE`'s note on why that is an instrument and not the
    suppression the `citations` lane refuses.
    """
    if typechecker is None:
        return
    from errors import ErrorReporter

    saved_reporter = typechecker.reporter
    typechecker.reporter = ErrorReporter("", "<mono-measure>")
    try:
        for key in list(mono.order):
            materialize_instance(mono, typechecker, mono.instances[key])
    finally:
        typechecker.reporter = saved_reporter


def run_monomorphization(program, namespace, reporter, verbose=False,
                         typechecker=None):
    """Phase 2. Returns the registry, or None if it produced errors."""
    mono = Monomorphizer(program, namespace, reporter, verbose=verbose)
    mono.run()
    if _MEASURE == "splice-all":
        measure_splice_all(mono, typechecker)
    return mono
