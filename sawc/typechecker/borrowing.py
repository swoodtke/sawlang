"""BORROWING STRUCTS: a type that holds a lent place (design 275 U3).

    borrows struct VectorIterator<T> {      // (1) the type declares its nature
        private vector: &Vector<T>          // (2) the field is a plain reference
        private index: Int
    }
    extension Vector<T: Copy> {
        public func iter(&self) borrows -> VectorIterator<T> {   // (3) the signature echoes it
            VectorIterator<T>(vector: lends self, index: 0)      // (4) the body proves it
        }
    }

Four spellings, each a Saw word or a design-141 word one position over, and
each one half of a rule this module enforces:

(1) `borrows struct` is design 130's `unsafe struct` shape — the parser's, and
    `parser/types.py:reject_reference_field` is where the field half lives.
(2) The field keeps the ordinary reference spelling. SHARED ONLY: a `&var`
    field, and an exclusive `lends` that would feed one, are refused, because a
    user iterator carrying `&var Collection` could reallocate the very
    collection an outer shared iterator is reading through its own field —
    recording the root alone would not catch it. (Distinct from `next(&var
    self)`: the cursor is the iterator's OWN state.)
(3) `borrows` in the effect slot on a VALUE-returning function. A `borrows`
    function either `lend`s exactly once (design 141) or RETURNS a borrowing
    struct, never both — `place_transform` splits on exactly that, by whether
    the body contains a `lend`.
(4) `lends self` at the init site is the body's proof, and THE ORIGIN IS A
    CHECKED COMPILER FACT: U3 admits the RECEIVER and nothing else, the
    receiver must be a REFERENCE receiver (`&self`), and the summary is
    recorded on the declaration as `Method.borrow_origin` — a DECLARED
    annotation field, so it rides `substitute_ast_types` through
    monomorphization and travels with an imported declaration exactly as
    `is_reference` does.

THE FENCE, and the ONE REJECTOR (obligation 1). A `borrows` call returning a
borrowing struct is legal in exactly ONE position: the DIRECT head of a `for`
whose RECEIVER is a PLACE rooted in a named binding. Every other position goes
through `reject_borrowing_value`, whose `POSITIONS` table is the matrix the
tests walk row by row. Type positions — a parameter, a field, a return, a type
argument, an existential — go through `reject_borrowing_type`, and the two are
one funnel in the sense that matters: one message vocabulary, one rule
sentence, one place to add a row.

NOTHING ERASES IT. A borrowing struct may not instantiate any type parameter,
be erased into an existential, or be named by a helper's parameter or return
type. Those are not a value-position refusal each; they are IMPOSSIBLE
SPELLINGS, refused at the DECLARATION that names the type — which is what makes
"a generic identity wrapper launders the value" unwritable rather than caught.

WHY THE FENCE IS SOUND AND A HANDLE WOULD NOT BE. The extent of a borrowing
struct's borrow is the window, and the window is a STATEMENT. Refused (user,
Sep 20) was the alternative — a handle that carries the borrow past the call
that made it, design 201's `TaskCaptureBorrow` extent generalized to any value.
That is a lifetime in disguise: design 201 gets away with it because a task
handle is fenced on every side, and a general iterator handle would owe that
fence at every position a value can go.
"""

from ast_nodes import (
    ArrayIndex, BindOptional, Block, ClosureExpr, ForceUnwrap, FunctionCall,
    Identifier, LendsExpr, MemberAccess, MethodCall, OptionalEvalExpr,
    ReferenceExpr, ReturnStatement, SawType, SelfExpr, StructInit, TupleIndex,
    TypeKind,
)
from ast_walk import child_nodes
from noescape import _MAX_ALIAS_DEPTH

# How deep `_first_borrowing_struct_in` follows a type's composition before
# it gives up — and giving up is `DEPTH_EXHAUSTED`, which every caller
# REFUSES (codex r2 #6: the old bound of eight answered "safe" past it, and
# nine nested `Vector`s hid a borrowing struct). Deeper than any type the
# corpus writes, so the answer is only ever reached by a pathological one.
_BORROWING_WALK_DEPTH = 32
DEPTH_EXHAUSTED = object()
from . import producers
from errors import ErrorKind
from windows import RECEIVER_ROOT, SHARED, WindowTable

#: The name of the hidden binding a window's RESOURCE lives in — exception e2,
#: never nameable in source (the lexer reserves the `__saw_`/`__` prefix for the
#: compiler). GENERIC by B1: the `for` client puts an iterator in it, a future
#: accessor client would put a lend result, and nothing downstream reads the
#: name to learn which.
WINDOW_RESOURCE = "__iter"


# --------------------------------------------------------------------------- #
# THE FENCE's position matrix — one row per refusal, one message each
# --------------------------------------------------------------------------- #
#
# Each row is `(key, what the author wrote)`. The sentence the rejector renders
# is the same for all of them — that is the point of one rejector — and the row
# supplies the phrase that names the position, so a reader is told WHICH of
# their positions the rule caught rather than being handed the rule alone.
#
# The four NARROW EXCEPTIONS are stated here so they license no user storage:
#   e1  construction and `return` inside the producing `borrows` function — its
#       ONLY legal return;
#   e2  the compiler's hidden window binding — a frame field in a driven body,
#       an alloca in a sync one, never nameable;
#   e3  the receiver position `&self` / `&var self` of the struct's OWN
#       extension methods (`next`);
#   e4  INSIDE those methods, the reference field read as a non-escaping
#       RE-BORROW (design 106's forwarding rules).

#: THE POSITIONS THE REJECTOR NAMES. Three, and that is deliberate: the fence
#: asks its question at the ONE place every expression's type is stamped, where
#: the parent slot is not in hand, so the sentence that matters is the RULE and
#: not the slot. The two named positions are the ones a CLIENT knows and that
#: diagnose a different ACT — a temporary receiver wants "bind the collection
#: first", and a head that is an expression wants "write the call itself".
#:
#: THE MATRIX IS THE TESTS, not this table. Every other position an author can
#: write — a `let`/`var` initializer, an argument, a `return`, a struct, enum,
#: tuple or collection-literal element, a closure capture or return, a spawn
#: argument or capture, a `move` operand, an assignment RHS, a `?.`/`??`
#: operand, a discarded statement — is a ROW of
#: `examples/errors/borrowing_struct_value_positions.saw`, and each of them
#: reaches this one message, which is what "one rejector" is for. The
#: IMPOSSIBLE SPELLINGS (a parameter, a field, a plain return, a type argument,
#: an existential, an `Item`) are refused at the DECLARATION instead — see
#: `reject_borrowing_type`.
POSITIONS = {
    'temporary':  "produced from a TEMPORARY receiver",
    'head-expr':  "produced by an `if` / `match` / block / `try` expression in "
                  "the head",
    'other':      "used outside a window head",
}

#: The one sentence every refusal states, so the rule reads the same wherever
#: it is met.
RULE = ("a borrowing struct holds a LENT PLACE, so its values live only inside "
        "their window — the extent is the `for` statement, which is what makes "
        "the borrow trackable without a lifetime")

#: The way out, likewise once.
FIX = ("write the call as the head of the `for` that consumes it "
       "(`for x in v.iter() { … }`); to hold a value past the loop, copy what "
       "you need out of it inside the body")

#: A WINDOW's introducer, per CLIENT. The diagnostics name "the window"
#: generically and take this phrase from the client, so the generic
#: scoped-borrow statement the follow-up specifies adds a row here rather than
#: forking every message.
_CLIENT_WORDING = {
    'for': "the `for` statement that iterates it",
    'generic': "the statement that opened it",
}

_CLIENT_FIX = {
    'for': ("a `for` over a borrowed iterator holds the collection for the "
            "whole loop, exactly as a `with_ref` window does — collect what "
            "you need first, or index the collection with a `while` loop if "
            "you must mutate it while walking it"),
    'generic': ("the window lasts for the whole statement that opened it; "
                "move the access before it or after it"),
}


class _WindowHeadMark:
    """`with checker._window_head(node):` — the node is a legal window head.

    Exactly one node, and only while it is being checked. The set is keyed by
    `id`, so nothing about the node's SHAPE grants the permission: an
    expression that merely looks like a head (a `v.iter()` written as an
    argument, say) is a different object and is refused.
    """

    __slots__ = ('checker', 'node', 'saved')

    def __init__(self, checker, node):
        self.checker = checker
        self.node = node

    def __enter__(self):
        self.saved = getattr(self.checker, '_window_head_ids', frozenset())
        self.checker._window_head_ids = self.saved | {id(self.node)}
        return self.node

    def __exit__(self, *exc):
        self.checker._window_head_ids = self.saved
        return False


class BorrowingMixin:
    # ==================================================================== #
    # Recognizing the type
    # ==================================================================== #

    def is_borrowing_struct(self, t) -> bool:
        """Does `t` NAME a borrowing struct — bare, or through a distinct alias?

        Keyed on the TYPE IDENTITY (design 144: defining module + name), never
        on a std visibility — a user `borrows struct` in another module is
        admitted and refused by exactly these rules.
        """
        return self.borrowing_struct_name(t) is not None

    def borrowing_struct_name(self, t, depth: int = 0):
        """The borrowing struct `t` RESOLVES to, by name, or None.

        THE ONE RESOLVER both boundaries ask — the declaration walk
        (`_borrowing_type_positions` through `_first_borrowing_struct_in`) and
        the value fence (`check_borrowing_fence`) — so a DISTINCT ALIAS of a
        borrowing struct (`type Alias = It`) is the borrowing struct at every
        position the bare name is. For one revision the two boundaries read
        the NOMINAL name, `get_struct_info("Alias")` answered None, and an
        iterator advertised `Alias` as its owned `Item`, yielded `Alias(self)`
        and stored it in an outer optional past the window (codex r1 #2).

        A distinct alias is its own type for every other rule (`Alias(it)` is
        the design-63 back-conversion, `Alias` and `It` do not unify), which is
        why this walks the alias to its underlying rather than asking the
        namespace to collapse it: the property being asked about is the
        UNDERLYING's nature, and an alias adds a name, never a home for a
        borrow.
        """
        if (t is None or t.kind != TypeKind.STRUCT or not t.struct_name
                or depth > _MAX_ALIAS_DEPTH):
            return None
        info = self.get_struct_info(t.struct_name)
        if info is not None:
            return (t.struct_name if getattr(info, 'is_borrowing', False)
                    else None)
        alias = self.get_type_alias_info(t.struct_name)
        if alias is None or alias.aliased_type is None:
            return None
        return self.borrowing_struct_name(alias.aliased_type, depth + 1)

    def reference_field_type(self, ftype):
        """THE RESOLVED FIELD CATEGORY: the shared or exclusive REFERENCE a
        borrowing struct's field holds, aliases resolved, or None for any
        other field.

        ONE answer for every consumer that asks "is this field the lent
        reference?" — the declaration check (`check_borrowing_struct_decl`),
        the producer proof (`_producer_paths_missing_origin`), the permission
        walk (`shared_reference_field_hop`) — and codegen's reference-field
        pointer check resolves the alias the same way before it reads the
        kind. For one revision each of them read the field's RAW kind while
        `_borrowing_field_referent` resolved the alias, so `source: OwnerRef`
        with `type OwnerRef = &Owner` was refused at the declaration as
        holding no lent place and would have been read three different ways
        past it (codex r2 #10).
        """
        resolved = ftype
        for _ in range(_MAX_ALIAS_DEPTH):
            if resolved is None or resolved.kind != TypeKind.STRUCT:
                break
            alias = self.get_type_alias_info(resolved.struct_name)
            if alias is None or alias.aliased_type is None:
                break
            resolved = alias.aliased_type
        if resolved is None or resolved.kind != TypeKind.REFERENCE:
            return None
        return resolved

    def _first_borrowing_struct_in(self, t, depth: int = 0):
        """The first borrowing struct reachable from `t`, None, or
        `DEPTH_EXHAUSTED`.

        Pre-order, and it recurses through every composition a type has —
        `Optional<It>`, `Result<It, E>`, `Vector<It>`, `Box<It>`, a tuple, an
        array, and a FUNCTION type's RETURN and PARAMETERS — because "may not
        instantiate ANY type parameter" is exactly the statement that no
        composition of it is nameable. A function type has NO exempt half
        (codex r4 #1): for one revision the walk answered None for the whole
        of `TypeKind.FUNCTION`, so `func bad() -> () -> It` passed the
        declaration fence although the brief lists a closure's return among
        the forbidden compositions. The reference no-escape walk
        (`noescape.first_reference_in`) DOES stop at a function type, and the
        two walks differ here on purpose: a reference is a legitimate closure
        PARAMETER (`(&T) -> R` is how every `with_ref` body is typed), while
        a borrowing struct is legitimate NOWHERE a closure can put it — a
        value handed INTO a closure's parameter is bound in a frame the
        window cannot see, exactly as one handed OUT of its return is — so
        `(It) -> Int` and `() -> It` are refused alike, and a nested function
        type (`() -> () -> It`, `((It) -> Int) -> Int`) recurses.

        A DISTINCT ALIAS is descended to its TARGET before its own (absent)
        parts are read (codex r2 #6): `type Hidden = Vector<It>` is a
        composition wearing a name, and for one revision this walk asked only
        whether the alias as a whole IS a borrowing struct and then descended
        the alias, which has no parts, so `Hidden` passed as a field and a
        parameter. And EXHAUSTING THE BOUND IS NOT AN ANSWER: the walk answers
        `DEPTH_EXHAUSTED`, which both callers refuse, where it used to answer
        "safe" past eight levels — nine nested `Vector`s hid an `It`.
        """
        if t is None:
            return None
        if depth > _BORROWING_WALK_DEPTH:
            return DEPTH_EXHAUSTED
        if self.is_borrowing_struct(t):
            return t
        if t.kind == TypeKind.STRUCT and t.struct_name:
            if self.get_struct_info(t.struct_name) is None:
                alias = self.get_type_alias_info(t.struct_name)
                if alias is not None and alias.aliased_type is not None:
                    return self._first_borrowing_struct_in(
                        alias.aliased_type, depth + 1)
        parts = []
        if t.kind in (TypeKind.OPTIONAL, TypeKind.REFERENCE,
                      TypeKind.EXISTENTIAL):
            parts.append(t.inner_type)
        if t.kind == TypeKind.ARRAY:
            parts.append(t.array_element_type)
        if t.kind == TypeKind.FUNCTION:
            parts.append(t.func_return_type)
            parts.extend(t.param_types or [])
        parts.extend(t.element_types or [])
        parts.extend(t.type_args or [])
        for part in parts:
            hit = self._first_borrowing_struct_in(part, depth + 1)
            if hit is not None:
                return hit
        return None

    def _reject_depth_exhausted(self, t, what, line, column) -> None:
        """The walk gave up before it could answer: refuse, naming the depth.
        A type nested past the bound cannot be PROVEN free of a borrowing
        struct, and a fence that answered "safe" there was no fence."""
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{what}: `{t}` nests types deeper than the borrowing-struct "
            f"walk follows ({_BORROWING_WALK_DEPTH} levels), so it cannot be "
            f"proven free of a `borrows struct` — and an unproven type is "
            f"refused, never admitted",
            line, column,
            hint="flatten the nesting, or name the inner type with a "
                 "`struct` of its own so each level is one declaration")

    # ==================================================================== #
    # THE ONE REJECTOR — value positions
    # ==================================================================== #

    def check_borrowing_fence(self, expr, result) -> None:
        """THE FENCE, at the ONE chokepoint every expression's type passes
        through (`_check_expression`'s stamp of `resolved_type`).

        A borrowing struct's value is legal in exactly one position — the
        DIRECT head of a `for` whose receiver is a place rooted in a named
        binding — plus the four narrow exceptions named in the module
        docstring. Asking the question HERE rather than at each construct is
        what makes the position list a matrix of TESTS rather than a matrix of
        checks: there is no `let`-arm, no argument-arm and no capture-arm to
        forget, because every one of them stamps a type through this line.

        The exceptions, in the order they are cheapest to answer:
          e1  inside the PRODUCING function — its construction and its return;
          e3  inside the borrowing struct's OWN extension methods, where `self`
              has that type;
          e2  the compiler's hidden window binding — not seen here at all,
              because the fence runs on the AUTHORED tree only (the E8
              exemption in `typechecker/core.py`);
          e4  the reference FIELD, which never has this type (it has the
              referent's, auto-dereferenced at the member access).
        """
        if getattr(self, 'exempt_statement_window', False):
            return
        found = self._first_borrowing_struct_in(result)
        if found is None:
            return
        if found is DEPTH_EXHAUSTED:
            self._reject_depth_exhausted(
                result, "this expression's type",
                getattr(expr, 'line', 0), getattr(expr, 'column', 0))
            return
        if id(expr) in getattr(self, '_window_head_ids', ()):
            return
        name = self.borrowing_struct_name(found)
        bare = found is result
        method = getattr(self, 'current_method', None)
        if method is not None:
            # e1: the producer's own construction and tail — the BARE struct,
            # judged by IDENTITY through any alias, never by spelling — and
            # ONLY the value being PROVED: a leaf of a returning path (the
            # tail, a `return`, an arm of a value branch on the way to
            # either), which is exactly the set `_producer_paths_missing_origin`
            # judges. Every other bare borrowing-typed expression in the body
            # meets the ordinary fence: `var held = other.iter()` inside a
            # producer stored a borrow and mutated its origin for one
            # revision, because the exemption read the RETURN TYPE and not
            # the position (codex r2 #7).
            ret = getattr(method, 'return_type', None)
            if (bare and self.borrowing_struct_name(ret) == name
                    and id(expr) in self._producer_proved_leaf_ids(method)):
                return
            # e3: the type's own extension methods — and ONLY the receiver
            # read itself (`self` as a receiver, a scrutinee, an operand; `&self`
            # as a re-borrow no safe declaration can accept). NOT a value that
            # merely HAS the type there: `Alias(self)`, `self.copy()`, a tuple
            # or an optional of `self` each package the receiver for escape,
            # and the exemption exists for reaching THROUGH `self`, not for
            # handing it out (codex r1 #2).
            recv = self._self_type_for_current_method()
            if (self.borrowing_struct_name(recv) == name
                    and self._is_receiver_read(expr)):
                return
        extra = ""
        if not bare:
            extra = (f" — here it is wrapped in `{result}`, and a composition "
                     f"of one outlives the window exactly as the bare value "
                     f"would")
        self.reject_borrowing_value(found, 'other', expr, extra=extra)

    @staticmethod
    def _is_receiver_read(expr) -> bool:
        """`self`, or `&self` / `&var self` — the receiver read as itself."""
        if isinstance(expr, SelfExpr):
            return True
        return isinstance(expr, ReferenceExpr) and isinstance(expr.expr, SelfExpr)

    def reject_borrowing_value(self, t, position, node, extra: str = "") -> None:
        """A borrowing-struct VALUE appeared somewhere that is not a window head.

        ONE message, one rule sentence, one fixit, anchored at the position the
        author wrote. `position` is a key of `POSITIONS`; adding a position
        means adding a row there, never a second message here.

        The two positions the CALLER can name are the head's own
        (`temporary`, `head-expr`), because the `for` adapter is the only place
        that knows a head was written and what was wrong with it. Everywhere
        else the position is `other`: the fence asks its question at the
        expression-type chokepoint, where the parent is not in hand and the
        sentence that matters is the RULE, not the slot.
        """
        where = POSITIONS.get(position, POSITIONS['other'])
        name = t.struct_name if t is not None else "a borrowing struct"
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"`{name}` is a `borrows struct` and may not be {where}: {RULE}"
            f"{extra}",
            getattr(node, 'line', 0), getattr(node, 'column', 0),
            hint=FIX)

    def reject_borrowing_type(self, t, what, line, column) -> None:
        """A DECLARATION named a borrowing struct in a position that stores or
        hands one back.

        The IMPOSSIBLE SPELLINGS half of the fence. A helper forwarding the
        result and a generic identity wrapper are not value-position rows at
        all — a borrowing struct cannot be a plain function's parameter or
        return type, nor a type argument — so the refusal lands at the HELPER's
        declaration, which is where the author can act on it.
        """
        found = self._first_borrowing_struct_in(t)
        if found is None:
            return
        if found is DEPTH_EXHAUSTED:
            self._reject_depth_exhausted(t, what, line, column)
            return
        names_it = ("is a `borrows struct`" if found is t
                    else f"names a `borrows struct` (`{found.struct_name}`)")
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{what} may not name a borrowing struct: `{t}` {names_it}, and "
            f"{RULE}. A type argument, an existential, a field, a parameter "
            f"and a plain return each outlive the window, so none of them can "
            f"name one — which is what makes a generic identity wrapper "
            f"unwritable rather than caught",
            line, column,
            hint="the one declaration that may name it is the `borrows` "
                 "producer that RETURNS it (`func iter(&self) borrows -> "
                 "VectorIterator<T>`) and the type's own extension methods")

    def validate_no_borrowing_struct_escape(self, program) -> None:
        """THE TYPE-POSITION half of the fence, over one program.

        Runs beside `_validate_no_ref_laundering_in_program` and over the SAME
        matrix (`NO_ESCAPE_POSITIONS`) — a struct field, an enum payload, every
        flavour of return, a static, an associated-type assignment, a
        generic-parameter default — PLUS the one position that matrix
        deliberately omits: a PARAMETER. A reference belongs in a parameter; a
        borrowing struct does not, because a parameter outlives nothing but it
        can be stored by the callee and the window's extent ends at a statement
        the callee cannot see.

        Two exemptions, and both are the producer's:
          * the PRODUCER's own return type — `func iter(&self) borrows -> It`
            is the one declaration that may name it;
          * the borrowing struct's OWN extension methods' receiver, which is
            not in this matrix at all (a receiver is not a declared parameter
            position here).

        The ASSOCIATED-TYPE row is what carries the ITEM-LIFETIME rule: a
        borrowing struct's `Iterator.Item` may be neither a reference (the
        no-escape walk's answer) nor a borrowing struct (this one's), so the
        loop variable OWNS what it is handed.
        """
        if getattr(self, 'exempt_statement_window', False):
            # E8: the post-transform program is the compiler's. The window's
            # resource IS a frame field there (exception e2 — a `Slot<It>` a
            # driven body holds inline, never nameable in source), which is the
            # ONE storage position the rule exists to describe rather than to
            # forbid. The authored program met this walk one pass earlier.
            return
        for t, what, line, column in self._borrowing_type_positions(program):
            self.reject_borrowing_type(t, what, line, column)

    def _borrowing_type_positions(self, program):
        """`(type, what, line, column)` for every declared position a borrowing
        struct may NOT name — the no-escape matrix plus PARAMETERS, minus the
        producer's own return.

        Written out rather than derived from `_no_escape_positions` because the
        two rules differ in exactly two rows and a filter over a shared
        generator would hide both: a PARAMETER is legal for a reference and not
        for a borrowing struct, and a `borrows` RETURN is legal for a borrowing
        struct and (in the `-> &T` spelling) for a reference.
        """
        def params_of(decl, label):
            for p in (getattr(decl, 'parameters', None) or []):
                if getattr(p, 'name', None) == 'self':
                    continue
                yield (getattr(p, 'type', None),
                       f"parameter `{p.name}` of {label}",
                       getattr(decl, 'line', 0), getattr(decl, 'column', 0))

        def returns_of(decl, label):
            # The producer's ONE legal return is the BARE borrowing struct —
            # exactly what `check_borrowing_producer` then proves (reference
            # receiver, `lends self` on every path) and records the origin
            # of. Nothing else a `borrows` declaration returns is exempt: a
            # COMPOSITE spelling (`It?`, `Optional<It>`, `Result<It, E>`,
            # `(It, Int)`, `Vector<It>`, `Box<It>`, an alias of any) is a
            # plain return that happens to sit on a `borrows` method, and it
            # takes the same refusal the same signature takes without the
            # word. For one revision the exemption keyed on `is_borrows`
            # alone while the producer check keyed on the bare struct, so
            # `borrows -> It?` fell between the two and compiled, and
            # `borrows -> Optional<It>` reached codegen and ICEd (codex r3
            # #2). The accessor lend forms (`borrows -> &T` and the
            # conditional `&T?`) go through the walk too, which refuses them
            # only when `T` names a borrowing struct — a place of that type
            # cannot exist, since no field or element may hold one.
            ret = getattr(decl, 'return_type', None)
            if (getattr(decl, 'is_borrows', False)
                    and self.is_borrowing_struct(ret)):
                return
            yield (ret, f"the return type of {label}",
                   getattr(decl, 'line', 0), getattr(decl, 'column', 0))

        for struct in getattr(program, 'structs', []) or []:
            for f in struct.fields:
                yield (f.type, f"field `{f.name}` of `{struct.name}`",
                       getattr(f, 'line', struct.line),
                       getattr(f, 'column', struct.column))
        for enum in getattr(program, 'enums', []) or []:
            for variant in enum.variants:
                for payload in (variant.associated_types or []):
                    name, pt = ((payload[0], payload[1])
                                if isinstance(payload, tuple)
                                else (variant.name, payload))
                    yield (pt, f"payload `{name}` of case `{variant.name}` in "
                               f"enum `{enum.name}`", enum.line, enum.column)
        for func in getattr(program, 'functions', []) or []:
            yield from returns_of(func, f"`{func.name}`")
            yield from params_of(func, f"`{func.name}`")
        for ext in getattr(program, 'extensions', []) or []:
            for m in (getattr(ext, 'methods', None) or []):
                yield from returns_of(m, f"`{m.name}`")
                yield from params_of(m, f"`{m.name}`")
            for assign in (getattr(ext, 'type_assignments', None) or []):
                yield (getattr(assign, 'assigned_type', None),
                       f"associated type `{assign.name}` of "
                       f"`{getattr(ext, 'struct_name', '?')}`",
                       getattr(assign, 'line', ext.line),
                       getattr(assign, 'column', ext.column))
        for trait in getattr(program, 'traits', []) or []:
            for tm in (getattr(trait, 'methods', None) or []):
                yield from returns_of(tm, f"`{trait.name}.{tm.name}`")
                yield from params_of(tm, f"`{trait.name}.{tm.name}`")
        for block in getattr(program, 'extern_blocks', []) or []:
            for fn in (getattr(block, 'functions', None) or []):
                yield from returns_of(fn, f"extern `{fn.name}`")
                yield from params_of(fn, f"extern `{fn.name}`")
        for static in getattr(program, 'statics', []) or []:
            yield (getattr(static, 'type', None), f"static `{static.name}`",
                   getattr(static, 'line', 0), getattr(static, 'column', 0))
        for decl in self._declarations_with_type_params(program):
            for tp in (getattr(decl, 'type_params', None) or []):
                if getattr(tp, 'is_const', False):
                    continue
                yield (getattr(tp, 'default', None),
                       f"the default of type parameter `{tp.name}`",
                       getattr(tp, 'line', 0) or getattr(decl, 'line', 0),
                       getattr(tp, 'column', 0) or getattr(decl, 'column', 0))

    # ==================================================================== #
    # (4) `lends self` — the origin proof
    # ==================================================================== #

    def _check_lends_expr(self, expr: LendsExpr):
        """`lends self` in the initializer of a borrowing struct's reference
        field. Returns `&Self`, or None after reporting.

        THE ORIGIN IS A CHECKED COMPILER FACT (codex c41 point 1). A `borrows`
        signature says a borrow exists; the call site must know WHICH root to
        charge. U3 admits ONE origin — the RECEIVER — so this refuses every
        other spelling by name rather than approximating a root walk.
        """
        method = getattr(self, 'current_method', None)
        producer = (method is not None
                    and getattr(method, 'is_borrows', False)
                    and self.is_borrowing_struct(
                        getattr(method, 'return_type', None)))
        if not producer:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`lends self` is the ORIGIN PROOF of a borrowing struct's "
                "construction and belongs only in a `borrows` function that "
                "RETURNS one",
                expr.line, expr.column,
                hint="declare the producer `func name(&self) borrows -> "
                     "TheBorrowingStruct` and initialize its reference field "
                     "with `lends self`")
            return None
        if not isinstance(expr.place, SelfExpr):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "U3 admits the receiver as the only borrow origin, so `lends "
                "self` is the only spelling: a projection of the receiver "
                "(`lends self.buffer`), another reference parameter, or a "
                "local names a root the CALL SITE cannot attribute, and the "
                "window charges the receiver place's root",
                expr.line, expr.column,
                hint="lend the ROOT, not the buffer — read through the "
                     "reference field on every access instead of snapshotting "
                     "what it points at")
            return None
        if not getattr(method, 'self_is_reference', False):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`lends self` requires a REFERENCE receiver: a by-value "
                "receiver's `self` is the callee's own local, not the caller's "
                "persistent storage, so there is no live borrowed origin to "
                "hand to the window",
                expr.line, expr.column,
                hint="declare the producer `func name(&self) borrows -> …`")
            return None
        if getattr(method, 'self_mutable', False):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`lends self` requires a SHARED receiver (`&self`): U3 is a "
                "shared-window feature, and an exclusive lend would feed a "
                "`&var` field a borrowing struct may not hold",
                expr.line, expr.column,
                hint="declare the producer `func name(&self) borrows -> …`; "
                     "mutating the produced value's OWN state stays ordinary "
                     "`&var self` on ITS methods")
            return None
        self_type = self._self_type_for_current_method()
        expr.referent_type = self_type
        return SawType(TypeKind.REFERENCE, inner_type=self_type,
                       reference_mutable=False)

    def _self_type_for_current_method(self):
        """`Self` as the body sees it — the receiver binding's own type."""
        info = self.current_scope.lookup('self')
        t = getattr(info, 'type', None) if info is not None else None
        if t is not None and t.kind == TypeKind.REFERENCE:
            return t.inner_type
        return t

    def check_borrowing_producer(self, method) -> None:
        """The declaration-side rules for a `borrows -> S` producer, and the
        recording of its ORIGIN.

        Run after the body is checked, so `lends self` has reported its own
        refusals first and this adds only what the body as a whole owes: a
        reference receiver, and EVERY reference field of the produced struct
        initialized with `lends self` on EVERY returning path.
        """
        if getattr(self, 'exempt_statement_window', False):
            # E8 again: `Slot<It>.take` in a post-transform frame is a
            # monomorphization of the compiler's OWN storage wrapper over the
            # window's resource, and its `-> T` is not a producer's return.
            return
        if getattr(method, 'place_type', None) is not None:
            # A LOWERED design-141 accessor, not a producer. The lowering
            # rewrote its signature into the window-closure form, whose result
            # is the caller's `__R` — and `__R` monomorphizes to whatever the
            # use site's expression produced, which in a post-transform driven
            # body is sometimes a borrowing struct itself (`for x in
            # self.items.value().iter()`, where the frame's `Slot` lends the
            # vector and the iterator is the window's value). `place_type` is
            # the lowering's own record that this declaration LENDS, and it is
            # what separates the two shapes after the fact exactly as the
            # presence of a `lend` separated them before it.
            return
        ret = getattr(method, 'return_type', None)
        if not self.is_borrowing_struct(ret):
            return
        if not getattr(method, 'is_borrows', False):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{method.name}` returns the borrowing struct "
                f"`{ret.struct_name}`, so its signature must say so: write "
                f"`borrows -> {ret}` in the effect slot",
                method.line, method.column,
                hint="a reader sees at the DECLARATION that the result "
                     "borrows the receiver, which is the whole of why the "
                     "word is there")
            return
        if not getattr(method, 'self_is_reference', False):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"a `borrows -> {ret}` producer needs a REFERENCE receiver "
                f"(`&self`): a by-value receiver's `self` is the callee's own "
                f"local, so there is no live borrowed origin for the window to "
                f"charge",
                method.line, method.column,
                hint="declare it `func {}(&self) borrows -> {}`".format(
                    method.name, ret))
            return
        if getattr(method, 'self_mutable', False):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"a `borrows -> {ret}` producer needs a SHARED receiver "
                f"(`&self`): U3 admits shared reference fields only, and an "
                f"exclusive receiver would be the origin of one this type may "
                f"not hold",
                method.line, method.column,
                hint="declare it `func {}(&self) borrows -> {}`".format(
                    method.name, ret))
            return
        missing = self._producer_paths_missing_origin(method, ret)
        if missing is not None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"U3 admits the receiver as the only borrow origin: every "
                f"returning path of `{method.name}` must construct "
                f"`{ret.struct_name}` with `lends self` in every reference "
                f"field{missing}",
                method.line, method.column,
                hint="a path that constructs the struct any other way, lends a "
                     "non-receiver place, a projection of `self`, another "
                     "reference parameter or a local has no root the call site "
                     "can charge")
            return
        # THE ORIGIN SUMMARY, recorded on the declaration (design 126's AST
        # contract). The call site reads it and substitutes it onto the
        # RECEIVER PLACE's root through design 141's root attribution.
        method.borrow_origin = RECEIVER_ROOT

    def _producer_paths_missing_origin(self, method, ret):
        """None when EVERY returning path is a well-formed origin proof, else a
        sentence naming the path that is not.

        BY PATH, NOT BY SCAN. The question is about the VALUE each returning
        path hands the caller, so this follows the paths: the body's tail and
        every `return` reachable in it (closures excluded — a closure's tail is
        its own return), and through each of those the ARMS of every value
        branch (`if`/`if let`/`match`/`try … catch`/a scoped block —
        `producers.branch_arm_sources`, the one table that says where a
        branch's arms live), peeling an auto-wrap where one sits. The LEAF of
        each path must be a construction of the produced struct whose every
        reference field is `lends self`; a leaf that is anything else — another
        accessor's call, a parameter, a local, a `try` over a foreign result —
        is refused AT THAT PATH, by line. For one revision the check scanned
        the body for constructions and passed when one well-formed one
        existed, so `if flag { It(source: lends self, …) } else { other.iter() }`
        passed on the strength of its true arm and the window then charged the
        wrong root (codex r1 #1).

        A diverging arm (a `panic`, a block whose every path returned) has no
        final expression and contributes no leaf; the `return`s inside it are
        paths of their own and are walked as such.

        THE RETURN TYPE IS RESOLVED FIRST (codex r2 #5): the proof is about
        the borrowing struct the declaration RESOLVES to, so an alias-spelled
        `borrows -> Alias` is proven against `It`'s fields — and "no struct
        information" is a REFUSAL, never a proof. For one revision this asked
        `get_struct_info` for the alias's own name, got None, and answered
        that every path was proven, so a producer whose one path returned
        `other.iter()` was certified. The reference fields are the RESOLVED
        category (`reference_field_type`), so an alias-spelled `&T` field is
        proven like a bare one.
        """
        name = self.borrowing_struct_name(ret)
        info = self.get_struct_info(name) if name is not None else None
        if info is None:
            return (f" — the declared return type `{ret}` resolves to no "
                    f"`borrows struct` the proof can read")
        ref_fields = [n for n in info.field_order
                      if self.reference_field_type(info.fields.get(n))
                      is not None]
        if not ref_fields:
            # A `borrows struct` with no reference field is design 130's rule-7
            # teaching error, reported at the TYPE. Nothing to prove here.
            return None
        results = list(self._returning_values_of(method.body))
        if not results:
            return (f" — no returning path of the body yields a value at all")
        for value in results:
            failure = self._producer_path_failure(value, name, ref_fields)
            if failure is not None:
                return failure
        return None

    def _producer_proved_leaf_ids(self, method):
        """The ids of the expressions `_producer_paths_missing_origin` judges
        — the LEAVES of every returning path, through auto-wraps and the arms
        of value branches — cached per method. The fence's e1 exemption is
        exactly this set: a value that is not on it is not being proved by
        the producer's rule and meets the ordinary fence."""
        cache = getattr(self, '_producer_leaf_cache', None)
        if cache is None:
            cache = self._producer_leaf_cache = {}
        key = id(method)
        leaves = cache.get(key)
        if leaves is not None:
            return leaves
        leaves = set()

        def collect(expr, depth=0):
            # Every node ON the path is proved — the wrap, the branch that
            # carries the arms, the conversion, the leaf — because each of
            # them is a bare borrowing-typed expression the fence will stamp.
            while isinstance(expr, self._ARM_WRAP_TYPES):
                leaves.add(id(expr))
                expr = expr.value
                if expr is None:
                    return
            leaves.add(id(expr))
            arms = producers.branch_arm_sources(expr)
            if arms is not None and depth < 64:
                for block in arms:
                    if block is None:
                        continue
                    result = (block.final_expr if isinstance(block, Block)
                              else block)
                    if result is not None:
                        collect(result, depth + 1)
                return
            converted = self._alias_conversion_operand(expr)
            if converted is not None:
                collect(converted, depth + 1)

        for value in self._returning_values_of(getattr(method, 'body', None)):
            collect(value)
        cache[key] = leaves
        return leaves

    @staticmethod
    def _returning_values_of(body):
        """The body's tail, then the value of every `return` reachable in it,
        in source order; a closure body is not walked (its tail returns from
        the closure)."""
        if body is None:
            return
        tail = getattr(body, 'final_expr', None)
        if tail is not None:
            yield tail
        stack = [body]
        seen = set()
        while stack:
            n = stack.pop()
            if n is None or id(n) in seen or isinstance(n, ClosureExpr):
                continue
            seen.add(id(n))
            if isinstance(n, ReturnStatement):
                if n.value is not None:
                    yield n.value
                continue
            stack.extend(reversed(list(child_nodes(n))))

    def _producer_path_failure(self, expr, name, ref_fields, depth: int = 0):
        """The sentence naming what is wrong with the path ending at `expr`,
        or None when its leaf (every leaf, through the arms) is a well-formed
        origin proof."""
        while isinstance(expr, self._ARM_WRAP_TYPES):
            expr = expr.value
            if expr is None:
                return None
        arms = producers.branch_arm_sources(expr)
        if arms is not None and depth < 64:
            for block in arms:
                if block is None:
                    continue
                result = (block.final_expr if isinstance(block, Block)
                          else block)
                if result is None:
                    continue            # diverging or returning: no leaf here
                failure = self._producer_path_failure(result, name, ref_fields,
                                                      depth + 1)
                if failure is not None:
                    return failure
            return None
        # A producer declared `borrows -> Alias` INHABITS the alias with the
        # design-63 back-conversion `Alias(<value>)`, so the value proved is
        # the conversion's argument: `Alias(It(source: lends self, …))` is the
        # construction, `Alias(other.iter())` is another producer's result
        # (codex r2 #5's program) and is refused as such.
        converted = self._alias_conversion_operand(expr)
        if converted is not None:
            return self._producer_path_failure(converted, name, ref_fields,
                                               depth + 1)
        line = getattr(expr, 'line', 0)
        if isinstance(expr, StructInit):
            built = self.borrowing_struct_name(
                SawType(TypeKind.STRUCT, struct_name=expr.struct_name))
            if built == name:
                supplied = dict(getattr(expr, 'field_inits', None) or ())
                for fname in ref_fields:
                    if not isinstance(supplied.get(fname), LendsExpr):
                        return (f" — the construction at line {line} "
                                f"initializes field `{fname}` with something "
                                f"other than `lends self`")
                return None
        return (f" — the path ending at line {line} yields "
                f"{self._describe_origin(expr)} rather than a construction of "
                f"`{name}` written in this body")

    def _alias_conversion_operand(self, expr):
        """The operand of a design-63 back-conversion `Alias(x)` when `expr`
        is one over a DISTINCT ALIAS, else None."""
        if not isinstance(expr, FunctionCall) or len(expr.arguments or ()) != 1:
            return None
        if self.get_type_alias_info(expr.name) is None:
            return None
        return expr.arguments[0].value

    @staticmethod
    def _describe_origin(expr) -> str:
        if isinstance(expr, MethodCall):
            return f"the call `.{expr.method_name}()`, another producer's result"
        if isinstance(expr, SelfExpr):
            return "`self`"
        if isinstance(expr, Identifier):
            return f"the binding `{expr.name}`"
        return f"a `{type(expr).__name__}`"

    # ==================================================================== #
    # THE REFERENCE FIELD'S PERMISSION — a hop through `&T` is read-only
    # ==================================================================== #

    def shared_reference_field_hop(self, target):
        """`(path, field_type)` for the first hop of the lvalue `target` that
        reads THROUGH a shared reference FIELD (`self.source` in
        `self.source.n`), or None.

        The auto-dereference at the member access (expressions.py's exception
        e4) makes the field read as the referent, exactly as a `&T` parameter
        reads — and a `&T` parameter's PERMISSION is carried by its binding,
        which every write rule consults. A field has no binding, so for one
        revision the permission was lost at the hop and a `&var self` cursor
        was taken as permission to write the referent: `self.source.n = 99`
        reached codegen and died there (codex r1 #10). This is that binding
        check one position over, and it is asked by ONE walk — the same hops
        `_immutable_lvalue_root` takes — from every entry that writes through a
        path:
          * `_check_write_target` (question 3b) — `x = v` / `x += v` in every
            target shape, the chain-assign entries included;
          * `_immutable_receiver_root` — a `&var self` method call, an
            exclusive place window, and `take()` on a receiver path;
          * `_check_reference_expr` — a `&var` argument.
        """
        hops = []
        node = target
        while True:
            if isinstance(node, MemberAccess):
                hops.append(node)
                node = node.object
            elif isinstance(node, TupleIndex):
                hops.append(node)
                node = node.tuple_expr
            elif isinstance(node, (ForceUnwrap, BindOptional)):
                hops.append(node)
                node = node.expr
            elif isinstance(node, OptionalEvalExpr):
                node = node.expr
            elif isinstance(node, ArrayIndex):
                hops.append(node)
                node = node.array_expr
            else:
                break
        if isinstance(node, Identifier):
            info = self.current_scope.lookup(node.name)
            current = getattr(info, 'type', None) if info is not None else None
            path = node.name
        elif isinstance(node, SelfExpr):
            current = self._self_type_for_current_method()
            path = 'self'
        else:
            return None
        hit = None
        for hop in reversed(hops):
            if isinstance(hop, ArrayIndex) and hit is not None:
                # THE STORAGE BOUNDARY `_immutable_lvalue_root` stops at
                # (codex r2 #9): indexing an `UnsafePointer` LEAVES the
                # referent's storage — the pointee is independently owned
                # memory the field merely names — so a write past it is not a
                # write through the shared field. `self.source.p[0] = 7` in
                # an `unsafe` method compiles; `self.source.n = 7` and a write
                # into an owned element (a `Vector` place charges the path)
                # stay refused. Decided on the CONTAINER's resolved type, the
                # fact that walk reads too.
                container = (self._resolve_type_alias(current)
                             if current is not None else None)
                if container is not None and container.kind == TypeKind.POINTER:
                    return None
            declared = self._hop_type(current, hop) if current is not None else None
            if isinstance(hop, MemberAccess):
                path = f"{path}.{hop.member}"
                ref = self.reference_field_type(declared)
                if (hit is None and ref is not None
                        and not ref.reference_mutable):
                    hit = (path, ref)
            elif isinstance(hop, TupleIndex):
                path = f"{path}.{hop.index}"
            elif isinstance(hop, ArrayIndex):
                path = f"{path}[…]"
            else:
                path = f"{path}!"
            current = declared
        return hit

    def reject_shared_reference_field_write(self, target, what: str,
                                            line, column) -> bool:
        """Refuse `what` (a verb phrase) through a shared reference field on
        the path `target`, naming the field and the rule. True when refused."""
        hop = self.shared_reference_field_hop(target)
        if hop is None:
            return False
        path, ref = hop
        self._error(
            ErrorKind.IMMUTABLE_ASSIGNMENT,
            f"cannot {what} through `{path}`: it is a shared reference field "
            f"(`{ref}`) of a `borrows struct`, and a borrowing struct's "
            f"reference field lends its referent READ-ONLY for the whole "
            f"window — a `for` window is shared, so no write reaches the "
            f"collection through the iterator, whatever the receiver's own "
            f"mode (`&var self` is permission to write the iterator's OWN "
            f"state, not what it borrows)",
            line, column,
            hint="mutate the iterator's own fields (`self.index`), never the "
                 "referent; a write to the collection belongs after the loop, "
                 "outside the window")
        return True

    def check_borrowing_struct_decl(self, struct) -> None:
        """A `borrows struct` with no reference field is design 130's rule-7
        teaching error: the declaration claims a nature its shape does not
        have, and reading the claim at every use site is the whole point."""
        if not getattr(struct, 'is_borrowing', False):
            return
        for f in struct.fields:
            if self.reference_field_type(f.type) is not None:
                return
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"`borrows struct {struct.name}` holds no lent place: not one of "
            f"its fields is a reference. The keyword says values of this type "
            f"carry a borrow, and every use site reads that claim — a type "
            f"that carries none should be a plain `struct`",
            struct.line, struct.column,
            hint=f"give it the reference field it borrows through "
                 f"(`private source: &TheCollection`), or drop `borrows` from "
                 f"the declaration")

    # ==================================================================== #
    # THE ROOT CHARGE, read at the Law of Exclusivity's existing access sites
    # ==================================================================== #

    def window_conflict(self, path, writes: bool):
        """The open statement window an access to `path` collides with, or None.

        THE FOUR ACCESS SITES that ask (obligation 1 — the same four design
        189's task-capture extent is read at, because a window is the Law read
        over a longer extent, not a second checker):

          1. a READ of a name — `expressions._check_identifier`
          2. a `move` — `expressions._check_move_expr`
          3. a CALL's access set — `types._check_call_exclusivity`, which is
             where a `&var` argument, a `&var self` receiver (`v.push`), an
             `o.take()` receiver, a closure's borrow CAPTURES and a design-201
             spawn argument all arrive
          4. a WRITE's target — `statements._check_write_target`, which is
             where `v = other`, `v[i] = x` and `v.field = x` arrive

        A window that is not open asks nothing; `writes=False` composes with a
        shared window, which is what makes a second `for` over the same root
        and an ordinary read inside the body legal.

        THE ROOT IS A BINDING, NOT A NAME. The path carries a name, and a name
        is not an identity: a legal refining shadow inside the body
        (`var v = v.copy()`, design 107) is a DIFFERENT binding that happens to
        be spelled the same, and the window borrows the one it charged. So the
        CURRENT binding of the path's root is resolved here and handed to the
        table, which compares identities before it compares projections —
        exactly as design 189's task borrow does (`_task_borrow_for` matches
        `b.root_id == var_info.binding_id`). An unresolvable root (`self`, a
        name the scope has already left) yields no identity and the table falls
        back to the path, which is the conservative answer.
        """
        table = getattr(self, '_windows', None)
        if table is None or not table.open or path is None:
            return None
        return table.conflict_for(path, writes,
                                  root_id=self._current_root_id(path[0]))

    def _current_root_id(self, root_name):
        """The STABLE IDENTITY the root NAME resolves to here, or None.

        THE ONE RESOLVER of a window root's identity — asked when a window
        OPENS (`open_for_window`) and at every access the table compares
        (`window_conflict`), so both sides answer the same question. A local
        is its `VariableInfo.binding_id`; a MODULE STATIC, which no scope
        holds, is the static symbol's own identity — distinct from any local
        of the same name, so a shadow `var ROOT = Owner(value: ROOT.value + 1)`
        inside a window on the static `ROOT` is an independent root and a
        write to the shadow is not a write to the static (codex r2 #8: for one
        revision the static resolved to NO identity, the table fell back to
        the path, and the shadow conflicted by text). A write to the STATIC
        itself inside its window resolves to the window's own identity and
        stays refused.
        """
        if root_name is None:
            return None
        info = self.current_scope.lookup(root_name)
        if info is not None:
            return getattr(info, 'binding_id', None)
        sym = self.namespace.get_static(root_name, self._accessor_vis_module())
        if sym is not None:
            return ('static', id(sym))
        return None

    def report_window_conflict(self, w, what: str, line, column,
                               root=None) -> None:
        """Report an access that collides with a live statement window.

        The vocabulary is the exclusivity vocabulary already in the checker;
        a window adds ONE sentence — the extent — exactly as design 189's task
        borrow does. The extent sentence NAMES THE WINDOW GENERICALLY and takes
        the introducer's wording from the CLIENT, so the generic scoped-borrow
        statement does not fork the messages.
        """
        if line in w.reported:
            return
        w.reported.add(line)
        name = root or w.renders_root()
        introducer = _CLIENT_WORDING.get(w.client, _CLIENT_WORDING['generic'])
        extent = (f"the window opened at line {w.line} borrows "
                  f"`{w.renders_root()}` for the whole of {introducer}")
        if what == 'move':
            message = (f"cannot `move` `{name}` while a window borrows it: "
                       f"{extent}")
        else:
            phrase = {
                'read': f"`{name}` cannot be read here",
                'write': f"`{name}` cannot be written here",
                'capture': f"`{name}` cannot be captured into another task here",
                'access': f"`{name}` cannot be accessed by reference here",
            }[what]
            message = f"exclusive access violation: {phrase} — {extent}"
        self._error(
            ErrorKind.EXCLUSIVITY_VIOLATION, message, line, column,
            hint=_CLIENT_FIX.get(w.client, _CLIENT_FIX['generic']))

    def check_window_access(self, path, writes: bool, what: str, line, column):
        """The one call the four access sites make. True iff it reported."""
        w = self.window_conflict(path, writes)
        if w is None:
            return False
        self.report_window_conflict(w, what, line, column,
                                    root=path[0] if path else None)
        return True

    # ==================================================================== #
    # THE for-head FENCE — a window head, and what a head may be
    # ==================================================================== #

    def borrowing_head_receiver(self, head):
        """The RECEIVER PLACE of a well-formed window head, or None.

        A head is a DIRECT call on a place ROOTED IN A NAMED BINDING — a local,
        a parameter (`&`, `&var`, or by value), `self`, or a field path of one
        (`st.patches`). Everything else is a refusal row, and the reason is one
        sentence: a temporary has no persistent storage to point into, so there
        is no root to charge.
        """
        if not isinstance(head, MethodCall):
            return None
        return head.object

    def open_for_window(self, stmt, iterable_type):
        """THE `for` ADAPTER to the window chokepoint.

        A THIN caller (the reuse obligation's word): it supplies the HEAD and
        the BODY, names its release operation, and reads back nothing
        for-specific. Everything it hands over — the root, the mode, the
        origin, the extent — is what ANY client supplies, and everything the
        chokepoint does with them is what every client gets.

        Returns the window, or None when this `for` opens none: a RANGE loop
        and an OWNED-iterator loop are ordinary loops (B4 — the fence applies
        to BORROWING results only), and a malformed head reports and opens
        nothing.

        B3's ACQUIRE sequence, in the order LANGUAGE_SPEC's "Argument
        Evaluation Order" already fixes and design 141's reference-argument
        rule already extends — nothing here changes evaluation order:

          A1  the receiver PLACE is resolved, and must be a persistent slot,
              which the direct-head rule is what guarantees;
          A2  the head's SHARED borrow of that root opens and spans the ENTIRE
              head call expression, ARGUMENTS INCLUDED — already true, because
              `_check_call_exclusivity` collects the receiver as a shared entry
              and design 199 pulls a nested `&var` in an argument into the same
              access set, so `v.iter(slow(&var v))` is refused there and a
              SUSPENDING argument is accepted (the U2 shape table's HOIST lifts
              it, and the static rule never consulted the lowering);
          A3  arguments evaluate left to right; a FAILING one exits before the
              producer runs, and no statement charge exists yet because this
              method has not been called;
          A4  the producer runs and returns the borrowing struct — which is the
              `iterable_type` handed in;
          A5  the head window hands off to the STATEMENT charge with no gap,
              and the resource is initialized into its persistent slot; only
              THEN is the window active.
        """
        if not self.is_borrowing_struct(iterable_type):
            return None
        if getattr(self, 'exempt_statement_window', False):
            # E8 (see `typechecker/core.py`): the post-transform re-check does
            # not re-charge a root. The record the authored pass stamped stays
            # on the statement — it is what the transform reads.
            return getattr(stmt, 'window', None)
        head = stmt.iterable
        receiver = self.borrowing_head_receiver(head)
        if receiver is None:
            self.reject_borrowing_value(iterable_type, 'head-expr', head)
            return None
        root = self.borrowing_head_root(receiver)          # A1
        if root is None:
            self.reject_borrowing_value(
                iterable_type, 'temporary', head,
                extra=". Bind the collection first (`let c = make()` then `for "
                      "x in c.iter()`): a temporary has no persistent storage "
                      "for the window to point into")
            return None
        table = self._window_table()
        w = table.open_window(                             # A5
            root_path=root,
            root_id=self._current_root_id(root[0]),
            mode=SHARED, origin=RECEIVER_ROOT, extent=stmt, client='for',
            line=head.line, column=head.column)
        table.activate(w, resource_name=WINDOW_RESOURCE,
                       resource_type=iterable_type)
        stmt.window = w
        return w

    def close_for_window(self, w) -> None:
        """RELEASE, with the `for` client's own cleanup operation: destroy the
        borrowing iterator, and only THEN end the root charge (design 275 U3's
        part (i) — the order matters because a hand-written `deinit` on a
        borrowing struct may still read through the reference).

        The ORDER is realized where the two events are — codegen for the sync
        form, the transform's exit-route closing for the split one. What
        happens HERE is the checker's half: the charge ends with the statement,
        on every route, which is the invariant ("no route may leave the root
        charge live past the statement") stated once.
        """
        if w is not None:
            self._window_table().close_window(w)

    def _window_head(self, node):
        """Name ONE expression node as a legal window head for the duration of
        its check. A context manager so the mark is exact: a nested `for` in an
        argument of the head would otherwise inherit the permission.
        """
        return _WindowHeadMark(self, node)

    def _window_table(self):
        """The function-local window table. Function-local for the reason
        `_task_borrows` is: a window's extent is a statement in ONE body, and a
        body is checked with none of its caller's open."""
        table = getattr(self, '_windows', None)
        if table is None:
            table = WindowTable()
            self._windows = table
        return table

    def borrowing_head_root(self, receiver):
        """Design 141's root attribution, applied to the head's receiver.

        `&v[i]` charges `v`; `v.iter()` charges `v`; `st.patches.iter()`
        charges the PATH `st.patches` (an enclosing-owner path per design
        8/10). Returns `(name, (hops...))` or None when the receiver is not
        rooted in a named binding.

        THE HANDOFF, named in the brief so this reuses the attribution rather
        than re-deriving a root walk: `_build_access_path` is the Law of
        Exclusivity's own answer to "which storage does this expression name",
        and a window charges exactly what a call's access set would.
        """
        return self._build_access_path(receiver)
