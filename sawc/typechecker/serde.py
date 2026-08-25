"""Serialize / Deserialize structural derivation (design 169 unit 2).

The design-48 Hashable derivation emits IR straight from the field layout: a
hash is a fold over machine words, so there is nothing a source-level body would
buy. Serialization is the opposite. A derived body is a sequence of fallible
calls whose failures propagate, and hand-building `Result` propagation in IR
would mean re-implementing `try` in llvmlite.

So these two derivations synthesize a real AST BODY and hand it to the ordinary
front end. Everything the bodies are made of — `try`, method calls, `for` over a
range, `guard let` — is already implemented, checked and lowered, which is also
why a derived body reports its own type errors against real source constructs.

The bodies are filled AFTER registration (`_synthesize_serde_bodies`), once every
struct, enum and trait is known: the walk needs field types, a nested type's
conformance, and an enum's raw backing, none of which is decided while the
extension that triggers the derivation is being registered. Registration itself
mints only the SIGNATURE, so callers and conformance checking see the method
immediately.

Shape (design 169 decision 2): a struct is an ARRAY of its stored fields in
declaration order. Exact-shape is the contract; there are no field names on the
wire and no schema evolution in v1.
"""

from ast_nodes import (
    ArrayIndex, Argument, Block, BoolLiteral, CastExpr, ExpressionStatement,
    ForLoop, GuardLetStatement, Identifier, IfExpr, IntLiteral, LetStatement,
    MemberAccess, MethodCall, MoveExpr, NoneLiteral, RangeExpr, ReferenceExpr,
    ReturnStatement, SawType, SelfExpr, StructInit, TryExpr, TypeKind,
)
from errors import ErrorKind


# The integer kinds a derived body reads back through a RANGE-CHECKED decoder
# call, mapped to the bounds it checks. A narrowing `as` would panic on a value
# outside the destination, and malformed input must never panic (design 169
# unit 4), so the bound is checked by the decoder and the cast that follows is
# provably in range.
_SIGNED_INT_BOUNDS = {
    TypeKind.INT8: (-128, 127),
    TypeKind.INT16: (-32768, 32767),
    TypeKind.INT32: (-2147483648, 2147483647),
    TypeKind.INT64: (-9223372036854775808, 9223372036854775807),
}

_UNSIGNED_INT_MAX = {
    TypeKind.UINT8: 255,
    TypeKind.UINT16: 65535,
    TypeKind.UINT32: 4294967295,
    TypeKind.UINT64: 18446744073709551615,
}


class SerdeDerivationError(Exception):
    """A member the field walk cannot express. Carries the prose the user sees."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class SerdeMixin:
    """Fills in the bodies of derived `serialize` / `deserialize` methods."""

    # ------------------------------------------------------------------ driver

    def _synthesize_serde_bodies(self, program):
        """Fill every derived serde body in `program`. Runs after registration."""
        for extension in getattr(program, 'extensions', []) or []:
            for method in extension.methods:
                if getattr(method, 'is_derived_serialize', False):
                    self._fill_serde_body(extension, method, encode=True)
                elif getattr(method, 'is_derived_deserialize', False):
                    self._fill_serde_body(extension, method, encode=False)

    def _fill_serde_body(self, extension, method, encode: bool):
        # Idempotent: registration re-enters over an AST it has already filled
        # (the coroutine and place transforms both do), and a body built twice
        # would double every write.
        if method.body is not None and method.body.statements:
            return
        type_name = extension.struct_name
        self._serde_tmp = 0
        try:
            if encode:
                stmts = self._serde_encode_body(type_name, extension)
            else:
                stmts = self._serde_decode_body(type_name, extension)
        except SerdeDerivationError as err:
            trait = "Serialize" if encode else "Deserialize"
            what = "serialize" if encode else "deserialize"
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot derive `{what}` for `{type_name}`: {err.reason}",
                extension.line, extension.column,
                hint=f"write `{what}` by hand, or give the member a type that "
                     f"conforms to `{trait}`",
                source_file=getattr(extension, 'source_file', None))
            # Leave a body that type-checks so the error is reported once.
            method.body = Block(statements=[self._ret_void(extension)],
                                final_expr=None,
                                line=extension.line, column=extension.column)
            return
        method.body = Block(statements=stmts, final_expr=None,
                            line=extension.line, column=extension.column)

    # ------------------------------------------------------- small AST helpers

    def _tmp(self, stem: str) -> str:
        """A body-unique local name. The double underscore keeps it out of the
        user's namespace and out of the design-100 shadowing rule's way."""
        self._serde_tmp += 1
        return f"__serde_{stem}{self._serde_tmp}"

    def _ln(self, node):
        return getattr(node, 'line', 0), getattr(node, 'column', 0)

    def _ret_void(self, at):
        line, col = self._ln(at)
        return ReturnStatement(value=None, line=line, column=col)

    def _try_stmt(self, call, at):
        """`try <call>` as a statement: propagate the failure, drop the Ok."""
        line, col = self._ln(at)
        return ExpressionStatement(
            expression=TryExpr(expr=call, variant="propagate",
                               line=line, column=col),
            line=line, column=col)

    def _try_expr(self, call, at):
        line, col = self._ln(at)
        return TryExpr(expr=call, variant="propagate", line=line, column=col)

    def _force_expr(self, call, at):
        """`try! <call>` — for a synthesized call whose error this body cannot
        carry (design 234 §5).

        The derived `deserialize` returns `Result<Self, DecodeError>`, and the
        only fallible call the DERIVATION itself makes is the vector `push`
        below, whose error is an `AllocError`. Routing it would mean naming
        `DecodeError`'s construction in code synthesized into the USER's module,
        where std.serde's fault vocabulary may not be imported at all. So the
        refusal panics, NAMING the error (DF-245b) — the same answer the
        collection literal's synthesized `push` gives, for the same reason: the
        author wrote no expression a `try` could sit on."""
        line, col = self._ln(at)
        return TryExpr(expr=call, variant="force", line=line, column=col)

    def _call(self, obj, name, args, at):
        line, col = self._ln(at)
        return MethodCall(object=obj, method_name=name, arguments=args,
                          line=line, column=col)

    def _arg(self, value, name=None):
        return Argument(value=value, name=name)

    def _ident(self, name, at):
        line, col = self._ln(at)
        return Identifier(name=name, line=line, column=col)

    def _int(self, value, at):
        line, col = self._ln(at)
        return IntLiteral(value=value, line=line, column=col)

    def _sink_ref(self, name, at):
        """`&var <name>` in argument position — the encoder/decoder forwarded on."""
        line, col = self._ln(at)
        return ReferenceExpr(expr=self._ident(name, at), mutable=True,
                             in_argument_position=True, line=line, column=col)

    def _cast(self, expr, kind, at):
        line, col = self._ln(at)
        return CastExpr(expr=expr, target_type=SawType(kind),
                        line=line, column=col)

    def _let(self, name, value, at, mutable=False, annotation=None):
        line, col = self._ln(at)
        return LetStatement(name=name, type_annotation=annotation, value=value,
                            mutable=mutable, line=line, column=col)

    def _decode_fault(self, fault: str, src: str, at):
        """`DecodeError(offset: <src>.offset(), fault: DecodeFault.<fault>)`."""
        line, col = self._ln(at)
        offset = self._call(self._ident(src, at), "offset", [], at)
        kind = MemberAccess(object=self._ident("DecodeFault", at),
                            member=fault, line=line, column=col)
        return StructInit(struct_name="DecodeError",
                          field_inits=[("offset", offset), ("fault", kind)],
                          line=line, column=col)

    # ------------------------------------------------------------ member lists

    def _serde_members(self, type_name, at):
        """`[(name, type)]` for a struct's stored fields, in declaration order.

        An enum is rejected here with the prose the caller reports: raw-backed
        enums take the dedicated path below, and a payload-carrying enum has no
        v1 derivation.
        """
        struct_info = self.namespace.structs.get(type_name)
        if struct_info is not None:
            return list(struct_info.fields.items())
        enum_info = self.namespace.enums.get(type_name)
        if enum_info is not None:
            raise SerdeDerivationError(
                "it is an enum with no raw backing, so its cases have no "
                "on-the-wire values (declare one, e.g. `enum "
                f"{type_name}: UInt8`, giving every case its number)")
        raise SerdeDerivationError(f"`{type_name}` is not a struct or enum")

    def _raw_backed_enum(self, type_name):
        """The `(enum symbol, backing type)` for a raw-backed enum, or None."""
        enum_info = self.namespace.enums.get(type_name)
        if enum_info is None:
            return None
        raw = getattr(enum_info, 'raw_type', None)
        if raw is None:
            return None
        return enum_info, raw

    # --------------------------------------------------------------- ENCODE

    def _serde_encode_body(self, type_name, extension):
        """The statements of a derived `serialize`."""
        sink = "to"
        backed = self._raw_backed_enum(type_name)
        if backed is not None:
            # A raw-backed enum IS its tag (design 145), so it encodes as the
            # one integer its case names — not as a one-item array.
            _info, raw = backed
            return self._encode_raw_enum(SelfExpr(line=extension.line,
                                                  column=extension.column),
                                         raw, sink, extension) + [
                self._ret_void(extension)]

        members = self._serde_members(type_name, extension)
        stmts = [self._try_stmt(
            self._call(self._ident(sink, extension), "begin_array",
                       [self._arg(self._int(len(members), extension))],
                       extension),
            extension)]
        for fname, ftype in members:
            value = MemberAccess(object=SelfExpr(line=extension.line,
                                                 column=extension.column),
                                 member=fname,
                                 line=extension.line, column=extension.column)
            try:
                stmts.extend(self._encode_value(value, ftype, sink, extension))
            except SerdeDerivationError as err:
                raise SerdeDerivationError(
                    f"field `{fname}` of type `{ftype}` {err.reason}")
        stmts.append(self._ret_void(extension))
        return stmts

    def _encode_raw_enum(self, value, raw, sink, at):
        """`try <sink>.write_uint(<value> as <raw> as UInt)`."""
        widened = self._cast(self._cast(value, raw.kind, at), TypeKind.UINT, at)
        return [self._try_stmt(
            self._call(self._ident(sink, at), "write_uint",
                       [self._arg(widened)], at), at)]

    def _encode_value(self, value, saw_type, sink, at):
        """Statements writing `value` (of `saw_type`) into `sink`."""
        if saw_type is None:
            raise SerdeDerivationError("has no resolved type")
        kind = saw_type.kind

        if kind == TypeKind.BOOL:
            return [self._try_stmt(
                self._call(self._ident(sink, at), "write_bool",
                           [self._arg(value)], at), at)]

        if kind == TypeKind.STRING:
            return [self._try_stmt(
                self._call(self._ident(sink, at), "write_text",
                           [self._arg(value)], at), at)]

        if kind == TypeKind.INT:
            return [self._try_stmt(
                self._call(self._ident(sink, at), "write_int",
                           [self._arg(value)], at), at)]

        if kind == TypeKind.UINT:
            return [self._try_stmt(
                self._call(self._ident(sink, at), "write_uint",
                           [self._arg(value)], at), at)]

        if kind in _SIGNED_INT_BOUNDS:
            return [self._try_stmt(
                self._call(self._ident(sink, at), "write_int",
                           [self._arg(self._cast(value, TypeKind.INT, at))], at),
                at)]

        if kind in _UNSIGNED_INT_MAX:
            return [self._try_stmt(
                self._call(self._ident(sink, at), "write_uint",
                           [self._arg(self._cast(value, TypeKind.UINT, at))], at),
                at)]

        if kind == TypeKind.OPTIONAL:
            return self._encode_optional(value, saw_type, sink, at)

        if kind == TypeKind.STRUCT and saw_type.struct_name == "Vector":
            return self._encode_vector(value, saw_type, sink, at)

        if kind == TypeKind.ENUM:
            backed = self._raw_backed_enum(saw_type.enum_name)
            if backed is None:
                return self._encode_conforming(value, saw_type.enum_name,
                                               sink, at)
            return self._encode_raw_enum(value, backed[1], sink, at)

        if kind == TypeKind.STRUCT:
            return self._encode_conforming(value, saw_type.struct_name, sink, at)

        raise SerdeDerivationError(
            "has no derived encoding (the field walk covers the integer types, "
            "`Bool`, `String`, `Optional`, `Vector`, raw-backed enums and any "
            "type conforming to `Serialize`)")

    def _encode_conforming(self, value, name, sink, at):
        if not self.namespace.type_conforms_to(name, "Serialize"):
            raise SerdeDerivationError("does not conform to `Serialize`")
        return [self._try_stmt(
            self._call(value, "serialize",
                       [self._arg(self._sink_ref(sink, at), name="to")], at), at)]

    def _encode_optional(self, value, saw_type, sink, at):
        """`if let p = <value> { <encode p> } else { try to.write_null() }`.

        An absent Optional is the null item, which is what makes a missing value
        distinguishable from a present one carrying a zero.
        """
        line, col = self._ln(at)
        inner = saw_type.inner_type
        if inner is None:
            raise SerdeDerivationError("is an Optional with no payload type")
        payload = self._tmp("opt")
        then_stmts = self._encode_value(self._ident(payload, at), inner, sink, at)
        else_stmts = [self._try_stmt(
            self._call(self._ident(sink, at), "write_null", [], at), at)]
        from ast_nodes import IfLetExpr
        expr = IfLetExpr(
            name=payload, optional_expr=value, mutable=False,
            then_branch=Block(statements=then_stmts, final_expr=None,
                              line=line, column=col),
            else_branch=Block(statements=else_stmts, final_expr=None,
                              line=line, column=col),
            line=line, column=col)
        return [ExpressionStatement(expression=expr, line=line, column=col)]

    def _encode_vector(self, value, saw_type, sink, at):
        """An array of exactly `len()` items, each written where it sits."""
        line, col = self._ln(at)
        args = saw_type.type_args or []
        if not args:
            raise SerdeDerivationError("is a Vector with no element type")
        elem = args[0]
        idx = self._tmp("i")
        length = self._call(value, "len", [], at)
        element = ArrayIndex(array_expr=value, index=self._ident(idx, at),
                             line=line, column=col)
        try:
            body_stmts = self._encode_value(element, elem, sink, at)
        except SerdeDerivationError as err:
            raise SerdeDerivationError(f"has element type `{elem}` which {err.reason}")
        return [
            self._try_stmt(
                self._call(self._ident(sink, at), "begin_array",
                           [self._arg(length)], at), at),
            ForLoop(variable=idx,
                    iterable=RangeExpr(start=self._int(0, at),
                                       end=self._call(value, "len", [], at),
                                       is_inclusive=False,
                                       line=line, column=col),
                    body=Block(statements=body_stmts, final_expr=None,
                               line=line, column=col),
                    line=line, column=col),
        ]

    # --------------------------------------------------------------- DECODE

    def _serde_decode_body(self, type_name, extension):
        """The statements of a derived `deserialize`."""
        src = "from"
        backed = self._raw_backed_enum(type_name)
        if backed is not None:
            _info, raw = backed
            name = self._tmp("case")
            stmts = self._decode_raw_enum(name, type_name, raw, src, extension)
            stmts.append(ReturnStatement(value=self._ident(name, extension),
                                         line=extension.line,
                                         column=extension.column))
            return stmts

        members = self._serde_members(type_name, extension)
        stmts = [self._try_stmt(
            self._call(self._ident(src, extension), "expect_array",
                       [self._arg(self._int(len(members), extension))],
                       extension),
            extension)]
        inits = []
        for fname, ftype in members:
            local = self._tmp("f")
            try:
                stmts.extend(self._decode_value(local, ftype, src, extension))
            except SerdeDerivationError as err:
                raise SerdeDerivationError(
                    f"field `{fname}` of type `{ftype}` {err.reason}")
            inits.append((fname, MoveExpr(variable=local,
                                          line=extension.line,
                                          column=extension.column)))
        stmts.append(ReturnStatement(
            value=StructInit(struct_name=type_name, field_inits=inits,
                             line=extension.line, column=extension.column),
            line=extension.line, column=extension.column))
        return stmts

    def _decode_raw_enum(self, name, enum_name, raw, src, at):
        """Read the tag, then map it back through the partial `from(raw:)`.

        An unrecognized value is DATA, not a trap (design 145), so it becomes a
        `DecodeError` naming the byte it was read at.
        """
        line, col = self._ln(at)
        max_value = _UNSIGNED_INT_MAX.get(raw.kind)
        if max_value is None:
            signed = _SIGNED_INT_BOUNDS.get(raw.kind)
            if signed is None:
                raise SerdeDerivationError(
                    f"has raw backing `{raw}`, which the field walk does not cover")
            raw_local = self._tmp("raw")
            stmts = [self._let(
                raw_local,
                self._try_expr(
                    self._call(self._ident(src, at), "read_int_range",
                               [self._arg(self._int(signed[0], at), name="min"),
                                self._arg(self._int(signed[1], at), name="max")],
                               at), at),
                at)]
            narrowed = self._cast(self._ident(raw_local, at), raw.kind, at)
        else:
            raw_local = self._tmp("raw")
            stmts = [self._let(
                raw_local,
                self._try_expr(
                    self._call(self._ident(src, at), "read_uint_max",
                               [self._arg(self._cast(self._int(max_value, at),
                                                     TypeKind.UINT, at),
                                          name="max")],
                               at), at),
                at)]
            narrowed = self._cast(self._ident(raw_local, at), raw.kind, at)
        stmts.append(GuardLetStatement(
            name=name,
            optional_expr=self._call(self._ident(enum_name, at), "from",
                                     [self._arg(narrowed, name="raw")], at),
            mutable=False,
            else_branch=Block(
                statements=[ReturnStatement(
                    value=self._decode_fault("UnknownCase", src, at),
                    line=line, column=col)],
                final_expr=None, line=line, column=col),
            line=line, column=col))
        return stmts

    def _decode_value(self, name, saw_type, src, at):
        """Statements binding `name` to a freshly read value of `saw_type`."""
        if saw_type is None:
            raise SerdeDerivationError("has no resolved type")
        kind = saw_type.kind
        at_line, at_col = self._ln(at)

        simple = {
            TypeKind.BOOL: "read_bool",
            TypeKind.STRING: "read_text",
            TypeKind.INT: "read_int",
            TypeKind.UINT: "read_uint",
        }.get(kind)
        if simple is not None:
            return [self._let(
                name,
                self._try_expr(self._call(self._ident(src, at), simple, [], at), at),
                at)]

        if kind in _SIGNED_INT_BOUNDS:
            low, high = _SIGNED_INT_BOUNDS[kind]
            wide = self._tmp("w")
            return [
                self._let(wide, self._try_expr(
                    self._call(self._ident(src, at), "read_int_range",
                               [self._arg(self._int(low, at), name="min"),
                                self._arg(self._int(high, at), name="max")],
                               at), at), at),
                self._let(name, self._cast(self._ident(wide, at), kind, at), at),
            ]

        if kind in _UNSIGNED_INT_MAX:
            wide = self._tmp("w")
            return [
                self._let(wide, self._try_expr(
                    self._call(self._ident(src, at), "read_uint_max",
                               [self._arg(self._cast(
                                   self._int(_UNSIGNED_INT_MAX[kind], at),
                                   TypeKind.UINT, at), name="max")],
                               at), at), at),
                self._let(name, self._cast(self._ident(wide, at), kind, at), at),
            ]

        if kind == TypeKind.OPTIONAL:
            return self._decode_optional(name, saw_type, src, at)

        if kind == TypeKind.STRUCT and saw_type.struct_name == "Vector":
            return self._decode_vector(name, saw_type, src, at)

        if kind == TypeKind.ENUM:
            backed = self._raw_backed_enum(saw_type.enum_name)
            if backed is not None:
                return self._decode_raw_enum(name, saw_type.enum_name,
                                             backed[1], src, at)
            return self._decode_conforming(name, saw_type.enum_name, src, at)

        if kind == TypeKind.STRUCT:
            return self._decode_conforming(name, saw_type.struct_name, src, at)

        raise SerdeDerivationError(
            "has no derived decoding (the field walk covers the integer types, "
            "`Bool`, `String`, `Optional`, `Vector`, raw-backed enums and any "
            "type conforming to `Deserialize`)")

    def _decode_conforming(self, name, type_name, src, at):
        if not self.namespace.type_conforms_to(type_name, "Deserialize"):
            raise SerdeDerivationError("does not conform to `Deserialize`")
        call = self._call(self._ident(type_name, at), "deserialize",
                          [self._arg(self._sink_ref(src, at), name="from")], at)
        return [self._let(name, self._try_expr(call, at), at)]

    def _decode_optional(self, name, saw_type, src, at):
        """`let f = if try from.at_null() { ...null...; None } else { ...payload... }`."""
        line, col = self._ln(at)
        inner = saw_type.inner_type
        if inner is None:
            raise SerdeDerivationError("is an Optional with no payload type")
        payload = self._tmp("p")
        then_block = Block(
            statements=[self._try_stmt(
                self._call(self._ident(src, at), "read_null", [], at), at)],
            final_expr=NoneLiteral(line=line, column=col),
            line=line, column=col)
        else_stmts = self._decode_value(payload, inner, src, at)
        else_block = Block(
            statements=else_stmts,
            final_expr=MoveExpr(variable=payload, line=line, column=col),
            line=line, column=col)
        cond = self._try_expr(
            self._call(self._ident(src, at), "at_null", [], at), at)
        return [self._let(
            name,
            IfExpr(condition=cond, then_branch=then_block,
                   else_branch=else_block, line=line, column=col),
            at, annotation=saw_type)]

    def _decode_vector(self, name, saw_type, src, at):
        """Read the declared length, then exactly that many elements."""
        line, col = self._ln(at)
        args = saw_type.type_args or []
        if not args:
            raise SerdeDerivationError("is a Vector with no element type")
        elem = args[0]
        count = self._tmp("n")
        idx = self._tmp("i")
        item = self._tmp("e")
        try:
            item_stmts = self._decode_value(item, elem, src, at)
        except SerdeDerivationError as err:
            raise SerdeDerivationError(f"has element type `{elem}` which {err.reason}")
        item_stmts = list(item_stmts) + [
            ExpressionStatement(
                expression=self._force_expr(
                    self._call(
                        self._ident(name, at), "push",
                        [self._arg(MoveExpr(variable=item, line=line, column=col))],
                        at),
                    at),
                line=line, column=col)]
        return [
            self._let(count, self._try_expr(
                self._call(self._ident(src, at), "begin_array", [], at), at), at),
            self._let(name,
                      StructInit(struct_name="Vector", field_inits=[],
                                 type_args=[elem], line=line, column=col),
                      at, mutable=True),
            ForLoop(variable=idx,
                    iterable=RangeExpr(start=self._int(0, at),
                                       end=self._ident(count, at),
                                       is_inclusive=False,
                                       line=line, column=col),
                    body=Block(statements=item_stmts, final_expr=None,
                               line=line, column=col),
                    line=line, column=col),
        ]
