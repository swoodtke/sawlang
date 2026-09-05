"""Signature visibility — "a public API needs public types" (user ruling, Aug 21).

A DECLARATION may not name a type LESS VISIBLE than the declaration's own
effective reach. A `public func`'s parameters and return must be `public`; a
`public(package)` declaration's signature types must be at least
`public(package)`; a `public` field's type must be at least as visible as the
field's effective reach. A PRIVATE declaration may name anything.

The rule exists because the alternative is a value a caller can hold and cannot
name: before it, `public func get(&self) -> Hidden` on a module-private
`Hidden` compiled, the caller could call `.doubled()` on the result, and the
PLACE path over the same type failed with a synthesized-closure type mismatch
that said nothing about visibility at all (DF-232o face 2). One refusal at the
declaration replaces all of that, and it lands where the author can act.

Shape: Rust's E0446, on design 219's precedent that a `public` declaration
HARD-REQUIRES what an internal one may infer — judged on the modifier as
WRITTEN, so it fires in a single-module program exactly as the public-generic
tier rule does.
"""

from typing import Optional, Tuple

from ast_nodes import (SawType, TypeKind, Visibility,
                       effective_field_visibility)
from errors import ErrorKind


# How wide each tier reaches, as a total order for the "at least as visible"
# comparison. PARENT sits below PACKAGE because a module's parent is inside its
# package wherever both words mean anything; the SCOPE half of the comparison
# (are these two tiers about the same package?) is not decided here — it is
# asked of design 80's own relation, which is the only thing that knows what a
# package is.
_REACH_RANK = {
    Visibility.PRIVATE: 0,
    Visibility.PARENT: 1,
    Visibility.PACKAGE: 2,
    Visibility.PUBLIC: 3,
}

# The prelude and the builtin traits are the language's own vocabulary. They are
# declared without a `public` marker in `builtin.saw` because nothing there was
# ever reached through the import machinery — the whole file is made directly
# accessible instead — so their recorded tier is PRIVATE and means nothing.
# Reading it literally would refuse `public func f(x: Vector<Int>)`.
_BUILTIN_MODULE = ("<std>", "builtin")


class SignatureVisibilityMixin:
    """THE SIGNATURE-VISIBILITY FUNNEL (obligation 1).

    ONE decision procedure — `_signature_type_visible_enough` — reached from ONE
    walk, `_check_signature_visibility_in_program`, over ONE position matrix,
    `SIGNATURE_VISIBILITY_POSITIONS`. Its entry points are the two places a
    compilation unit's declarations are known: `TypeChecker.check` (the
    single-file path, and the builtins) and `TypeChecker.check_module` (one
    module of a multi-module unit). Both call it at the same seam — after
    extensions are registered and after `_canonicalize_module_types`, so every
    named type in a signature carries its design-144 identity and every
    declaration's own tier is on its AST node.

    THE POSITIONS IT REACHES are `SIGNATURE_VISIBILITY_POSITIONS` below, one row
    per place a declaration names a type, in `_signature_visibility_positions`
    order and covered row by row by
    `examples/private_in_public_positions_error.saw`.

    THE POSITIONS IT DELIBERATELY DOES NOT REACH. A function BODY may name
    anything: a local, an annotation on a `let`, a temporary, a closure's
    inferred type — none of them are on the declaration's surface, and every use
    of them is already gated by design 80 where it happens. A PRIVATE
    declaration's signature is unconstrained for the same reason, which is what
    makes "narrow the declaration" a real fix rather than a dead end. An
    extension's RECEIVER type is not judged: extending a private type is the
    private-declaration case, and the receiver CAP below already makes every
    member of such a type private. A CONFORMANCE (`extension T: Trait`) is not
    judged either — the orphan rule already pins it to the module owning `T` or
    `Trait`, and a conformance mints a vtable rather than a nameable surface. An
    `extern "C"` declaration carries no visibility modifier at all, so it is
    private by construction and there is nothing here to ask about it; its C
    surface is `@export`'s business (design 58), which has its own type
    whitelist.
    """

    # One row per position; `_signature_visibility_positions` yields exactly
    # these, in this order, and nothing else. Every row is covered by
    # `examples/private_in_public_positions_error.saw` unless named otherwise.
    SIGNATURE_VISIBILITY_POSITIONS = (
        # row                                 covered by
        ("free function parameter",           "positions: `take`"),
        ("free function return",              "positions: `give`, `wrapped`"),
        ("free function generic bound",       "positions: `bounded`"),
        ("free function generic default",     "positions: `defaulted`"),
        ("extension method parameter",        "positions: `Exposed.init`"),
        ("extension method return",           "positions: `Exposed.peek`, "
                                              "`Exposed.blank`"),
        # DF-245a: an `init`'s return was skipped while it could only ever name
        # the receiver. The fallible form names an ERROR type beside it.
        ("extension init return",             "positions: `Exposed.init`'s "
                                              "`Result<Exposed, Hidden>`"),
        ("extension method lent place",       "conformance/B22: `Carrier.at`"),
        ("extension generic bound/default",   "private_in_public_extension_"
                                              "surface_error"),
        ("extension associated type",         "private_in_public_extension_"
                                              "surface_error"),
        ("struct field",                      "positions: `Exposed.slot`"),
        ("struct generic bound/default",      "positions: `Boxed`"),
        ("enum case payload",                 "positions: `Tagged.One`"),
        ("static declaration",                "positions: `LIMIT`"),
        ("type alias target",                 "positions: `Alias`"),
        ("trait requirement",                 "positions: `Facade.make`"),
        ("trait parent",                      "positions: `Facade`"),
    )

    # ------------------------------------------------------------------ #
    # The reach of a declaration, and of a type.
    # ------------------------------------------------------------------ #

    def _decl_reach(self, decl, cap: Optional[Visibility] = None,
                    vis: Optional[Visibility] = None
                    ) -> Tuple[Visibility, Tuple[str, ...]]:
        """A declaration's EFFECTIVE reach: `(tier, defining module)`.

        `cap` is the tier of the thing that gates reachability from outside —
        a member's own struct or enum, a requirement's trait. Design 80 already
        says a `public` member of a non-public type is inert, so the effective
        reach is the NARROWER of the two and the rule never demands more of a
        field than its struct can hand out.

        `vis` overrides the tier read off the declaration, for the one kind of
        declaration whose tier is not simply what it carries: a struct FIELD,
        which since design 258 INHERITS its type's tier when unmarked. The
        caller passes `effective_field_visibility`'s answer rather than a second
        copy of the rule.
        """
        if vis is None:
            vis = getattr(decl, 'visibility', Visibility.PRIVATE)
        vis = vis or Visibility.PRIVATE
        if cap is not None and _REACH_RANK[cap] < _REACH_RANK[vis]:
            vis = cap
        return (vis, self._vis_module_for_source(
            getattr(decl, 'source_file', None)))

    def _named_type_reach(self, name: str):
        """`(tier, defining module, kind word)` for a named type, or None when
        nothing here declares it.

        None means the name is a type PARAMETER, a forward reference this module
        cannot see, or a compiler-internal type — never a refusal. A name that
        does not resolve is somebody else's diagnostic.
        """
        for lookup, word in ((self.get_struct_info, "struct"),
                             (self.get_enum_info, "enum"),
                             (self.get_trait_info, "trait"),
                             (self.get_type_alias_info, "type alias")):
            try:
                info = lookup(name)
            except Exception:
                info = None
            if info is None:
                continue
            module = tuple(getattr(info, 'def_module', ()) or ())
            if module == _BUILTIN_MODULE:
                # The prelude's own vocabulary — see `_BUILTIN_MODULE`.
                return (Visibility.PUBLIC, module, word)
            vis = getattr(info, 'visibility', Visibility.PRIVATE)
            return (vis or Visibility.PRIVATE, module, word)
        return None

    def _signature_type_visible_enough(
            self, type_vis: Visibility, type_module: Tuple[str, ...],
            decl_vis: Visibility, decl_module: Tuple[str, ...]) -> bool:
        """THE DECISION PROCEDURE: is a type reachable from everywhere the
        declaration naming it is?

        Reuses design 80's relation rather than restating it. The tier ranks
        answer "is the type's reach at least as WIDE"; `_visibility_relation_
        allows` answers "and is it the same SCOPE" — a `public(package)` type of
        another package covers nothing here, and a `public(parent)` declaration
        is reached from its parent module, which is the accessor the relation is
        asked about.
        """
        if decl_vis == Visibility.PRIVATE:
            # A private declaration may name anything: nobody outside the module
            # can reach it, so nothing it names can escape.
            return True
        if type_vis == Visibility.PUBLIC:
            return True
        if _REACH_RANK[type_vis] < _REACH_RANK[decl_vis]:
            return False
        # Same tier or wider, so the only question left is whether the scopes
        # nest. The WITNESS accessor is the widest module the declaration
        # reaches: its parent for `public(parent)`, and its own module for
        # `public(package)` — whose package the relation then compares against
        # the type's.
        witness = (decl_module[:-1] if decl_vis == Visibility.PARENT
                   else decl_module)
        return self._visibility_relation_allows(type_module, type_vis, witness)

    # ------------------------------------------------------------------ #
    # The walk.
    # ------------------------------------------------------------------ #

    def _sigvis_exempt(self) -> bool:
        """The whole-pass exemptions — TWO of the prelude gate's three.

        A compiler-synthesized declaration answers for itself (the coroutine
        transform's frames hold std internals in fields no author wrote), and
        the post-transform re-check reads exactly that output.

        `_checking_builtins` is deliberately NOT among them. The prelude gate
        exempts std because std's own bodies name std types by construction,
        which says nothing about whether a std SIGNATURE may hand out a std
        internal — and it may not: design 82 makes each std file its own module,
        so std is under this rule like any other package. The sweep that turned
        the rule on found four std declarations returning a private iterator
        type, and widening those types is what the rule asked for.
        """
        return bool(getattr(self, 'exempt_prelude_gate', False)
                    or self._in_synthesized_context())

    def _check_signature_visibility_in_program(self, program) -> None:
        """Run the rule over every declared position of one module's AST."""
        if self._sigvis_exempt():
            return
        for (t, what, decl_what, reach, line, column, source_file) in (
                self._signature_visibility_positions(program)):
            # Design 255 / SL-4: this walk runs over a whole module AFTER its
            # bodies, so design 192's expression/statement breadcrumb is empty
            # and a use-site diagnostic raised from one of the lookups below
            # (a type-name AMBIGUITY, most of all) has nothing to anchor on.
            # The position is right here.
            self._name_anchor = (line, column)
            try:
                self._check_signature_type(t, what, decl_what, reach,
                                           line, column, source_file)
            finally:
                self._name_anchor = None

    def _check_signature_type(self, t, what: str, decl_what: str,
                              reach, line: int, column: int,
                              source_file: Optional[str], depth: int = 0
                              ) -> None:
        """Judge every NAMED type reachable from `t` against `reach`.

        The walk recurses because a type argument, an optional payload, a tuple
        element, an array element and a function type's parts are all positions
        the author wrote a name in: `Vector<Hidden>` exposes `Hidden` exactly as
        a bare `Hidden` does.
        """
        if t is None or depth > 8:
            return
        if isinstance(t, str):
            # A bound / parent trait: a bare trait name, not a `SawType`.
            self._judge_signature_name(t, what, decl_what, reach,
                                       line, column, source_file)
            return
        if not isinstance(t, SawType):
            return
        if t.kind != TypeKind.TYPE_PARAM:
            for name in (t.struct_name, t.enum_name, t.existential_trait):
                if name:
                    self._judge_signature_name(name, what, decl_what, reach,
                                               line, column, source_file)
        for child in (t.inner_type, t.array_element_type, t.func_return_type):
            self._check_signature_type(child, what, decl_what, reach,
                                       line, column, source_file, depth + 1)
        for child in ((t.type_args or []) + (t.element_types or [])
                      + (t.param_types or [])):
            self._check_signature_type(child, what, decl_what, reach,
                                       line, column, source_file, depth + 1)

    def _judge_signature_name(self, name: str, what: str, decl_what: str,
                              reach, line: int, column: int,
                              source_file: Optional[str]) -> None:
        found = self._named_type_reach(name)
        if found is None:
            return
        type_vis, type_module, word = found
        decl_vis, decl_module = reach
        if self._signature_type_visible_enough(
                type_vis, type_module, decl_vis, decl_module):
            return
        key = (source_file, line, column, name, what)
        if key in self._sigvis_reported:
            return
        self._sigvis_reported.add(key)
        from type_identity import display_name
        short = display_name(name)
        # Name the OWNER only when it is somewhere else: "private in `this
        # module`" is noise in the single-module case, which is most of them.
        owner = ("" if tuple(type_module) == tuple(decl_module)
                 else f" in `{self._module_label(type_module)}`")
        # Design 258 ruling 5: a FIELD has a third way out the other positions do
        # not — it can be narrowed WITHOUT narrowing anything else, because
        # `private` is exactly the spelling for "this field is not on the type's
        # surface". Worth naming, because a field that reaches this refusal is
        # most often one whose tier the author never chose: it inherited it.
        narrow = ("mark the field `private`" if decl_what.startswith("field `")
                  else "narrow the declaration")
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{decl_what} is {self._vis_word(decl_vis)}, but {what} names "
            f"`{short}`, which is {self._vis_word(type_vis)}{owner} — a "
            f"public API needs public types",
            line, column,
            hint=f"either widen the type — mark the {word} `{short}` "
                 f"`{self._vis_word(decl_vis)}`{owner} — or {narrow}, so its "
                 f"signature stays where `{short}` can be "
                 f"named. A caller that can reach a declaration must be able to "
                 f"name every type in its signature",
            source_file=source_file,
        )

    # ------------------------------------------------------------------ #
    # The position matrix.
    # ------------------------------------------------------------------ #

    def _signature_visibility_positions(self, program):
        """Yield `(type, what, decl_what, reach, line, column, source_file)` for
        every row of `SIGNATURE_VISIBILITY_POSITIONS`, in that order.

        `type` is a `SawType` or — for a bound and a parent trait, which are
        spelled as bare names — a `str`.
        """
        vis_of = lambda d: getattr(d, 'visibility', Visibility.PRIVATE)

        # 1-2. Free functions: parameters, return, and their own generics.
        for func in getattr(program, 'functions', []):
            if getattr(func, 'is_mono_instance', False):
                continue
            if getattr(func, 'is_synthesized', False):
                continue
            reach = self._decl_reach(func)
            src = getattr(func, 'source_file', None)
            pos = (getattr(func, 'line', 0), getattr(func, 'column', 0))
            what_decl = f"function `{func.name}`"
            # See the extension-method arm below for the lowered `borrows` case.
            place = getattr(func, 'place_type', None)
            for p in getattr(func, 'parameters', []):
                if place is not None and p.name == "__window":
                    continue
                yield (getattr(p, 'type', None), f"parameter `{p.name}`",
                       what_decl, reach, pos[0], pos[1], src)
            if place is not None:
                yield (place, "the type it lends", what_decl, reach,
                       pos[0], pos[1], src)
            else:
                yield (getattr(func, 'return_type', None), "the return type",
                       what_decl, reach, pos[0], pos[1], src)
            yield from self._type_param_positions(
                func, what_decl, reach, pos, src)

        # 3-4. Extension methods — instance, `static` and `init` alike. The cap
        # is the RECEIVER's tier: a public method of a private type is inert.
        for ext in getattr(program, 'extensions', []):
            cap = self._receiver_tier(ext)
            widest = Visibility.PRIVATE
            for method in getattr(ext, 'methods', []):
                if getattr(method, 'is_synthesized', False):
                    continue
                if getattr(method, 'place_var_twin', False):
                    continue
                reach = self._decl_reach(method, cap=cap)
                if _REACH_RANK[reach[0]] > _REACH_RANK[widest]:
                    widest = reach[0]
                src = (getattr(method, 'source_file', None)
                       or getattr(ext, 'source_file', None))
                pos = (getattr(method, 'line', ext.line),
                       getattr(method, 'column', ext.column))
                kind = ("init" if getattr(method, 'is_init', False)
                        else "static method" if getattr(method, 'is_static', False)
                        else "method")
                what_decl = f"{kind} `{ext.struct_name}.{method.name}`"
                # A `borrows` accessor arrives here LOWERED: the place transform
                # has already turned `borrows -> T` into a `__window: (&var T)
                # sync -> __R` parameter (design 141). Judge `place_type`, which
                # is the `T` the author wrote, and skip the synthesized
                # parameter — a diagnostic naming `__window` would point at a
                # spelling no author can see.
                place = getattr(method, 'place_type', None)
                for p in getattr(method, 'parameters', []):
                    if place is not None and p.name == "__window":
                        continue
                    yield (getattr(p, 'type', None), f"parameter `{p.name}`",
                           what_decl, reach, pos[0], pos[1], src)
                if place is not None:
                    yield (place, "the type it lends", what_decl, reach,
                           pos[0], pos[1], src)
                else:
                    # An `init` is on this list too, since DF-245a. Its declared
                    # return used to be the RECEIVER and nothing else, so judging
                    # it could only restate the cap — but the fallible form names
                    # an ERROR type beside the receiver, and a `public init(...)
                    # -> Result<Exposed, Hidden>` would hand every caller a value
                    # whose failure they cannot name. The receiver form stays
                    # inert exactly as it was: `cap` is the receiver's own tier,
                    # so a return naming the receiver can never out-reach it.
                    yield (getattr(method, 'return_type', None),
                           "the return type", what_decl, reach,
                           pos[0], pos[1], src)
                yield from self._type_param_positions(
                    method, what_decl, reach, pos, src)
            # The extension's OWN generics constrain every call that reaches any
            # of its methods, so they are judged at the widest reach among them.
            if getattr(ext, 'type_params', None):
                yield from self._type_param_positions(
                    ext, f"extension `{ext.struct_name}`'s surface",
                    (widest, self._vis_module_for_source(
                        getattr(ext, 'source_file', None))),
                    (ext.line, ext.column), getattr(ext, 'source_file', None))
            # An associated-type assignment names the type every use of that
            # associated name resolves to.
            for assign in (getattr(ext, 'type_assignments', None) or []):
                yield (getattr(assign, 'assigned_type', None),
                       f"associated type `{assign.name}`",
                       f"extension `{ext.struct_name}`'s surface",
                       (widest, self._vis_module_for_source(
                           getattr(ext, 'source_file', None))),
                       getattr(assign, 'line', ext.line),
                       getattr(assign, 'column', ext.column),
                       getattr(ext, 'source_file', None))

        # 6. Struct fields — capped by the struct's own tier, and since design
        # 258 DEFAULTING to it: a bare field inherits its declaring type's tier,
        # so its type must keep up with that tier. This is ruling 5, and it is
        # the one place inheritance turns something that used to compile into a
        # refusal — a public struct's bare field naming a private type was fine
        # while the field was private, and is a refusal now.
        for struct in getattr(program, 'structs', []):
            src = getattr(struct, 'source_file', None)
            cap = vis_of(struct)
            for field_decl in struct.fields:
                reach = self._decl_reach(
                    field_decl, cap=cap,
                    vis=effective_field_visibility(field_decl, cap))
                if not getattr(field_decl, 'source_file', None):
                    reach = (reach[0], self._vis_module_for_source(src))
                yield (field_decl.type, "its type",
                       f"field `{field_decl.name}` of `{struct.name}`", reach,
                       getattr(field_decl, 'line', struct.line),
                       getattr(field_decl, 'column', struct.column), src)
            yield from self._type_param_positions(
                struct, f"struct `{struct.name}`",
                (vis_of(struct), self._vis_module_for_source(src)),
                (struct.line, struct.column), src)

        # 7. Enum case payloads — a variant follows its enum's tier.
        for enum in getattr(program, 'enums', []):
            src = getattr(enum, 'source_file', None)
            reach = (vis_of(enum), self._vis_module_for_source(src))
            for variant in enum.variants:
                for payload in (variant.associated_types or []):
                    pname, pt = ((payload[0], payload[1])
                                 if isinstance(payload, tuple)
                                 else (variant.name, payload))
                    yield (pt, f"payload `{pname}` of case `{variant.name}`",
                           f"enum `{enum.name}`", reach,
                           enum.line, enum.column, src)
            yield from self._type_param_positions(
                enum, f"enum `{enum.name}`", reach,
                (enum.line, enum.column), src)

        # 8. Statics.
        for static in getattr(program, 'statics', []):
            src = getattr(static, 'source_file', None)
            yield (getattr(static, 'type', None), "its type",
                   f"static `{static.name}`",
                   (vis_of(static), self._vis_module_for_source(src)),
                   getattr(static, 'line', 0), getattr(static, 'column', 0),
                   src)

        # 9. Type aliases — the TARGET is what every use of the name resolves
        # to, so it is on the alias's own surface.
        for type_def in getattr(program, 'type_definitions', []):
            src = getattr(type_def, 'source_file', None)
            yield (getattr(type_def, 'defined_type', None), "its target",
                   f"type alias `{type_def.name}`",
                   (vis_of(type_def), self._vis_module_for_source(src)),
                   getattr(type_def, 'line', 0), getattr(type_def, 'column', 0),
                   src)

        # 10-11. Trait requirements and parent traits — the TRAIT's own tier is
        # the bar, since a requirement has no modifier of its own.
        for trait in getattr(program, 'traits', []):
            src = getattr(trait, 'source_file', None)
            reach = (vis_of(trait), self._vis_module_for_source(src))
            for tm in trait.methods:
                pos = (getattr(tm, 'line', trait.line),
                       getattr(tm, 'column', trait.column))
                what_decl = f"trait `{trait.name}`"
                for p in getattr(tm, 'parameters', []):
                    yield (getattr(p, 'type', None),
                           f"parameter `{p.name}` of requirement `{tm.name}`",
                           what_decl, reach, pos[0], pos[1], src)
                yield (getattr(tm, 'return_type', None),
                       f"the return type of requirement `{tm.name}`",
                       what_decl, reach, pos[0], pos[1], src)
            for parent in (getattr(trait, 'parent_traits', None) or []):
                yield (parent, "its parent trait", f"trait `{trait.name}`",
                       reach, trait.line, trait.column, src)
            yield from self._type_param_positions(
                trait, f"trait `{trait.name}`", reach,
                (trait.line, trait.column), src)

    def _type_param_positions(self, decl, what_decl, reach, pos, src):
        """A generic parameter's BOUND and DEFAULT, for one declaration.

        Both are named types the caller meets: a bound is what an argument must
        satisfy, and a default is a type substituted into the declaration with
        no argument position ever written.
        """
        for tp in (getattr(decl, 'type_params', None) or []):
            if getattr(tp, 'is_const', False):
                continue
            line = getattr(tp, 'line', 0) or pos[0]
            column = getattr(tp, 'column', 0) or pos[1]
            for bound in (getattr(tp, 'bounds', None) or []):
                yield (bound, f"the bound on type parameter `{tp.name}`",
                       what_decl, reach, line, column, src)
            yield (getattr(tp, 'default', None),
                   f"the default of type parameter `{tp.name}`",
                   what_decl, reach, line, column, src)

    def _receiver_tier(self, ext) -> Visibility:
        """The tier of the type an extension extends — the cap on every member
        it declares (design 80: a `public` member of a non-public type is
        legal but inert). PUBLIC when the receiver cannot be found, which is
        somebody else's diagnostic."""
        found = self._named_type_reach(getattr(ext, 'struct_name', '') or '')
        return found[0] if found is not None else Visibility.PUBLIC
