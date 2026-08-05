"""
Saw Language Parser
Recursive descent parser that builds an AST from tokens.
"""

from typing import List, Optional
from lexer import Token, TokenType
from ast_nodes import (
    Program, Function, Parameter, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    WhileExpr, BreakStatement, ContinueStatement, ForLoop,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation, Identifier,
    BinaryOp, UnaryOp, MoveExpr, CastExpr, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex,
    MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    GuardLetStatement, RangeExpr,
    Struct, StructField,
    Enum, EnumVariant, MatchExpr, MatchArm,
    Extension, Method, MethodCall, SelfExpr,
    Trait, TraitMethod, AssociatedType, TypeAssignment, TypeDefinition,
    ExternFunction, ExternBlock,
    SawType, TypeKind, Argument, TypeParameter,
    ClosureExpr, ClosureParam,
    ImportDecl, ModuleDecl, ExportDecl, Visibility,
    FUNC_STATIC_ATTRIBUTES, EXTENSION_ATTRIBUTES
)
from .types import TypeParsingMixin, GenericListTrailingComma
from .declarations import DeclarationsMixin
from .statements import StatementsMixin
from .expressions import ExpressionsMixin


class DocBlock:
    """A run of contiguous doc-comment lines (design 121).

    `kind` is 'doc' (a `///` run, documenting the declaration that follows) or
    'module' (a `//!` run, documenting the file). `text` is the run's bodies
    joined with newlines. A blank line, an ordinary comment, or a change of kind
    ends the run — all three show up as a gap in the lexer's line numbering.
    """
    __slots__ = ("kind", "text", "line", "column", "end_line")

    def __init__(self, kind, text, line, column, end_line):
        self.kind = kind
        self.text = text
        self.line = line
        self.column = column
        self.end_line = end_line


def group_doc_comments(doc_comments) -> List[DocBlock]:
    """Group the lexer's per-line doc trivia into blocks, in source order."""
    blocks: List[DocBlock] = []
    lines: List[str] = []
    cur = None
    for dc in doc_comments or []:
        if cur is not None and dc.kind == cur.kind and dc.line == cur.end_line + 1:
            lines.append(dc.text)
            cur.end_line = dc.line
            continue
        if cur is not None:
            cur.text = "\n".join(lines)
        cur = DocBlock(dc.kind, "", dc.line, dc.column, dc.line)
        lines = [dc.text]
        blocks.append(cur)
    if cur is not None:
        cur.text = "\n".join(lines)
    return blocks


class Parser(ExpressionsMixin, StatementsMixin, DeclarationsMixin, TypeParsingMixin):
    # Program lists whose last element is the declaration a top-level `///` block
    # documents (design 121). Imports, exports, module declarations, extern
    # blocks and static_asserts are deliberately absent — they are not
    # documentable, so a `///` in front of one is an unattached-doc error.
    DOC_DECL_LISTS = ("functions", "structs", "enums", "traits", "extensions",
                      "type_definitions", "statics")

    def __init__(self, tokens: List[Token], source_file: str = "",
                 doc_comments=None):
        self.tokens = tokens
        self.pos = 0
        # Flag to control trailing closure parsing (disabled in if/while/guard conditions)
        self.allow_trailing_closure = True
        # Track source file for error reporting
        self.source_file = source_file
        # Newlines-inside-brackets (design 129). `_nl_suppressed[i]` is True for a
        # NEWLINE token whose innermost enclosing bracket is `(` or `[`;
        # `_generic_depth` adds the same suppression inside a COMMITTED generic
        # `<...>` list, which only the parser can recognize. Both feed
        # `_is_skippable_newline`, which `current`/`peek`/`advance` honor.
        self._generic_depth = 0
        self._nl_suppressed, self._unclosed_openers = self._index_brackets()
        # Doc-comment trivia (design 121). Blocks are indexed by the token they
        # precede; a block nobody claims is reported after the parse.
        self.doc_blocks = group_doc_comments(doc_comments)
        self._doc_taken = [False] * len(self.doc_blocks)
        self._doc_at_token = self._index_doc_blocks()

    # Bracket kinds, by opener. `(` and `[` make an enclosed NEWLINE insignificant
    # (design 129); `{` does NOT — a block or closure is a statement container, so
    # its newlines keep terminating statements.
    _BRACKET_PAIRS = {
        TokenType.LPAREN: TokenType.RPAREN,
        TokenType.LBRACKET: TokenType.RBRACKET,
        TokenType.LBRACE: TokenType.RBRACE,
    }
    _NEWLINE_SUPPRESSING_OPENERS = (TokenType.LPAREN, TokenType.LBRACKET)

    def _index_brackets(self):
        """Precompute the bracket structure of the token stream (design 129).

        Returns `(nl_suppressed, unclosed_openers)`:
        - `nl_suppressed[i]` — True for a NEWLINE token sitting directly inside a
          `(`/`[` group. A `{` pushed on top of a paren restores significance, so
          a multi-statement closure passed as an argument still parses as a block.
        - `unclosed_openers` — the `(`/`[` tokens left open at EOF, in source
          order, paired with their token index. They anchor the unclosed-bracket
          diagnostic at the OPENER instead of letting it drift (design 119's
          interpolation-brace precedent). Because such an opener is never closed,
          it encloses every later token, so "innermost opener before position p"
          is just the last entry with index < p.

        The bracket structure is purely positional, so it is computed once here
        rather than tracked through the parser's many bracket sites (and through
        its backtracking, which would corrupt a mutable stack). A closer that does
        not match the open group is left for the parser's own diagnostics.
        """
        n = len(self.tokens)
        nl_suppressed = [False] * n
        stack = []  # (opener TokenType, index, Token)
        for i, tok in enumerate(self.tokens):
            ttype = tok.type
            if ttype == TokenType.NEWLINE:
                if stack and stack[-1][0] in self._NEWLINE_SUPPRESSING_OPENERS:
                    nl_suppressed[i] = True
            elif ttype in self._BRACKET_PAIRS:
                stack.append((ttype, i, tok))
            elif ttype in (TokenType.RPAREN, TokenType.RBRACKET, TokenType.RBRACE):
                if stack and self._BRACKET_PAIRS[stack[-1][0]] == ttype:
                    stack.pop()
        unclosed = [(i, tok) for (opener, i, tok) in stack
                    if opener in self._NEWLINE_SUPPRESSING_OPENERS]
        return nl_suppressed, unclosed

    def _index_doc_blocks(self) -> dict:
        """Map token index -> doc block index: each block belongs to the first
        non-NEWLINE token that starts on a later line than the block's last line.

        Two blocks separated by a blank line resolve to the SAME token; the later
        (adjacent) one wins, which is what leaves the detached earlier block
        unclaimed and therefore reported.
        """
        index = {}
        n = len(self.tokens)
        cursor = 0
        for b, block in enumerate(self.doc_blocks):
            while cursor < n and (self.tokens[cursor].type == TokenType.NEWLINE
                                  or self.tokens[cursor].line <= block.end_line):
                cursor += 1
            if cursor < n:
                index[cursor] = b
        return index

    def _take_doc(self, kind: str = "doc") -> Optional[DocBlock]:
        """Claim the doc block attached to the token at the parse position, if it
        is of `kind`. Claiming marks it used; an unclaimed block is an error."""
        b = self._doc_at_token.get(self.pos)
        if b is None:
            return None
        block = self.doc_blocks[b]
        if block.kind != kind or self._doc_taken[b]:
            return None
        self._doc_taken[b] = True
        return block

    def _take_module_docs(self) -> Optional[str]:
        """Claim the `//!` blocks at the very top of the file and join them.

        A module doc is legal only ahead of every declaration, so the leading run
        of `module` blocks qualifies exactly while it ends before the file's first
        real token. Blocks separated by a blank line join with a blank line; a
        `//!` anywhere else stays unclaimed and is reported.
        """
        first = None
        for tok in self.tokens:
            if tok.type != TokenType.NEWLINE:
                first = tok
                break
        texts = []
        for b, block in enumerate(self.doc_blocks):
            if block.kind != "module":
                break
            if first is None or first.line <= block.end_line:
                break
            self._doc_taken[b] = True
            texts.append(block.text)
        return "\n\n".join(texts) if texts else None

    def _release_doc(self, block: DocBlock):
        """Un-claim a block the caller could not attach, so the post-parse sweep
        reports it as an unattached doc comment."""
        for b, other in enumerate(self.doc_blocks):
            if other is block:
                self._doc_taken[b] = False
                return

    @staticmethod
    def doc_text(block: Optional[DocBlock]) -> Optional[str]:
        return block.text if block is not None else None

    def _unattached_doc_errors(self) -> List[str]:
        """One message per doc block no declaration claimed, in source order."""
        errors = []
        for b, block in enumerate(self.doc_blocks):
            if self._doc_taken[b]:
                continue
            if block.kind == "module":
                msg = ("module doc comment (`//!`) must appear before the first "
                       "declaration in the file")
            else:
                msg = ("doc comment is not followed by a documentable "
                       "declaration")
            errors.append(f"Parse error at {block.line}:{block.column}: {msg}")
        return errors

    def error(self, msg: str):
        token = self.current()
        # A parse that reaches `}` or EOF while a `(`/`[` is still open has run
        # past the real mistake — those two tokens cannot occur inside a bracket
        # group that eventually closes. Report the OPENER instead (design 129,
        # mirroring the design-119 interpolation-brace precedent), since newline
        # suppression is what let the parse get this far.
        if token.type in (TokenType.RBRACE, TokenType.EOF):
            opener = self._innermost_unclosed_opener()
            if opener is not None:
                self._unclosed_bracket_error(opener)
        raise SyntaxError(f"Parse error at {token.line}:{token.column}: {msg}")

    def _is_skippable_newline(self, pos: int) -> bool:
        """True if the token at `pos` is a NEWLINE the current context ignores."""
        if self.tokens[pos].type != TokenType.NEWLINE:
            return False
        return self._generic_depth > 0 or self._nl_suppressed[pos]

    def _skip_suppressed_newlines(self):
        """Advance past NEWLINEs that are insignificant here (design 129).

        Every token accessor funnels through this, so a wrapped argument list,
        collection literal, parameter list, or generic list reads exactly like the
        single-line spelling. Idempotent, and it only moves FORWARD over tokens
        the current context would ignore anyway — so the many `saved = self.pos` /
        `self.pos = saved` backtracking sites stay correct.
        """
        pos = self.pos
        n = len(self.tokens)
        while pos < n and self._is_skippable_newline(pos):
            pos += 1
        self.pos = pos

    def current(self) -> Token:
        self._skip_suppressed_newlines()
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]  # EOF

    def peek(self, offset: int = 0) -> Token:
        self._skip_suppressed_newlines()
        n = len(self.tokens)
        pos = self.pos
        for _ in range(offset):
            pos += 1
            while pos < n and self._is_skippable_newline(pos):
                pos += 1
        if 0 <= pos < n:
            return self.tokens[pos]
        return self.tokens[-1]

    def advance(self) -> Token:
        token = self.current()
        self.pos += 1
        return token

    def match(self, *types: TokenType) -> bool:
        return self.current().type in types

    def expect(self, token_type: TokenType, msg: str = None) -> Token:
        if self.current().type != token_type:
            # A closer that never arrives is reported at its OPENER (design 129):
            # with newlines suppressed inside brackets, an unclosed `(`/`[` runs
            # the parser far past the mistake, so "Expected ')'" would land on
            # whatever token happened to stop it. Mirrors the design-119
            # interpolation-brace precedent.
            if token_type in (TokenType.RPAREN, TokenType.RBRACKET):
                opener = self._innermost_unclosed_opener(
                    TokenType.LPAREN if token_type == TokenType.RPAREN
                    else TokenType.LBRACKET)
                if opener is not None:
                    self._unclosed_bracket_error(opener)
            if msg:
                self.error(msg)
            else:
                self.error(f"Expected {token_type.name}, got {self.current().type.name}")
        return self.advance()

    def _innermost_unclosed_opener(self, kind: TokenType = None) -> Optional[Token]:
        """The innermost never-closed `(`/`[` enclosing the parse position.

        A never-closed opener encloses every token after it, so "innermost before
        `self.pos`" is just the last entry with a smaller index. `kind` narrows
        the search to one bracket type.
        """
        found = None
        for index, tok in self._unclosed_openers:
            if index >= self.pos:
                break
            if kind is None or tok.type == kind:
                found = tok
        return found

    def _unclosed_bracket_error(self, opener: Token):
        open_ch, close_ch = (('(', ')') if opener.type == TokenType.LPAREN
                             else ('[', ']'))
        raise SyntaxError(
            f"Parse error at {opener.line}:{opener.column}: "
            f"unclosed `{open_ch}` — no matching `{close_ch}` before the end of "
            f"the file (a line break inside brackets does not close them)")

    def skip_newlines(self):
        while self.match(TokenType.NEWLINE):
            self.advance()

    def match_ident(self, value: str) -> bool:
        """Check if current token is IDENT with the given value (for context-sensitive keywords)."""
        return self.current().type == TokenType.IDENT and self.current().value == value

    def expect_ident(self, value: str, msg: str = None) -> Token:
        """Expect an IDENT token with the given value (for context-sensitive keywords)."""
        if not self.match_ident(value):
            if msg:
                self.error(msg)
            else:
                self.error(f"Expected '{value}', got {self.current().type.name}")
        return self.advance()

    def parse_type_params(self) -> List[TypeParameter]:
        """Parse optional type parameters: <T, U, ...>

        A `<` in declaration position is unambiguously generic, so newlines inside
        the list are insignificant (design 129) and a trailing comma is rejected,
        matching `_parse_type_args`.
        """
        if not self.match(TokenType.LT):
            return []

        self.advance()  # consume '<'
        self._generic_depth += 1
        try:
            params = []

            # Parse first type parameter
            params.append(self._parse_single_type_param())

            # Parse additional type parameters
            while self.match(TokenType.COMMA):
                comma = self.advance()
                if self.match(TokenType.GT):
                    raise GenericListTrailingComma(
                        f"Parse error at {comma.line}:{comma.column}: a trailing "
                        f"comma is not allowed in a generic parameter list "
                        f"(it is allowed in `(...)` and `[...]` lists)")
                params.append(self._parse_single_type_param())

            self.expect(TokenType.GT, "Expected '>' after type parameters")
        finally:
            self._generic_depth -= 1
        return params

    def _parse_visibility(self) -> Visibility:
        """Parse optional visibility modifier: public, public(package), public(parent)."""
        if not self.match(TokenType.PUBLIC):
            return Visibility.PRIVATE

        self.advance()  # consume 'public'

        # Check for public(package) or public(parent)
        if self.match(TokenType.LPAREN):
            self.advance()  # consume '('
            if not self.match(TokenType.IDENT):
                self.error("Expected 'package' or 'parent' after 'public('")
            modifier = self.current().value
            self.advance()

            if modifier == "package":
                visibility = Visibility.PACKAGE
            elif modifier == "parent":
                visibility = Visibility.PARENT
            else:
                self.error(f"Unknown visibility modifier: public({modifier}). Expected 'package' or 'parent'")

            self.expect(TokenType.RPAREN, "Expected ')' after visibility modifier")
            return visibility

        return Visibility.PUBLIC

    def _parse_single_type_param(self) -> TypeParameter:
        """Parse a single type parameter: T or T: Bound + OtherBound"""
        start = self.current()
        name_token = self.expect(TokenType.IDENT, "Expected type parameter name")

        # Parse optional bounds: T: Trait1 + Trait2
        bounds = []
        if self.match(TokenType.COLON):
            self.advance()
            # Parse first bound
            bound_token = self.expect(TokenType.IDENT, "Expected trait name after ':'")
            bounds.append(bound_token.value)
            # Parse additional bounds
            while self.match(TokenType.PLUS):
                self.advance()
                bound_token = self.expect(TokenType.IDENT, "Expected trait name after '+'")
                bounds.append(bound_token.value)

        # Parse optional default: `A: Allocator = Global` (design 37). Default
        # type parameters — a TYPE after `=`, never a value. Enables the allocator
        # to be omitted at hosted reference sites (`Vector<Int>`) while the type
        # system still carries the full `Vector<Int, Global>` identity.
        default = None
        if self.match(TokenType.ASSIGN):
            self.advance()  # consume '='
            default = self.parse_type()

        return TypeParameter(
            name=name_token.value,
            bounds=bounds,
            default=default,
            line=start.line,
            column=start.column
        )

    # Maximum syntax errors collected before bailing out of a single file.
    MAX_PARSE_ERRORS = 10

    def _at_toplevel_start(self) -> bool:
        """True if the current token can begin a top-level declaration."""
        t = self.current()
        if t.type in (TokenType.FUNC, TokenType.STRUCT, TokenType.ENUM,
                      TokenType.EXTENSION, TokenType.TRAIT, TokenType.TYPE,
                      TokenType.EXTERN, TokenType.STATIC, TokenType.PUBLIC,
                      TokenType.AT):
            return True
        if t.type == TokenType.IDENT and t.value in ("import", "module", "export"):
            return True
        return False

    def _synchronize(self):
        """Recover from a syntax error by skipping to the next top-level
        declaration boundary (`func`/`struct`/`enum`/`extension`/`trait`/
        `type`/`extern`/`import`/`module`/`export` at brace depth 0).

        Always consumes at least one token so the parse loop makes forward
        progress (otherwise re-dispatching on the same offending token would
        loop forever). Braces are tracked so a top-level keyword nested inside a
        malformed body is not mistaken for a boundary; an unmatched closing
        brace at depth 0 also ends recovery.
        """
        depth = 0
        first = True  # skip the offending token before honoring any boundary
        while not self.match(TokenType.EOF):
            t = self.current()
            if t.type == TokenType.LBRACE:
                depth += 1
                self.advance()
            elif t.type == TokenType.RBRACE:
                if depth > 0:
                    depth -= 1
                    self.advance()
                else:
                    # Stray closing brace at depth 0: consume it and resume.
                    self.advance()
                    return
            elif not first and depth == 0 and self._at_toplevel_start():
                return
            else:
                self.advance()
            first = False

    def _parse_toplevel_decl(self, p: Program):
        """Parse ONE top-level declaration, attaching the `///` block in front of
        it (design 121). The declaration itself is parsed by
        `_dispatch_toplevel_decl`; the doc lands on whichever declaration list
        grew, so attributes and a `public` prefix between the doc and the item
        make no difference. A doc in front of a non-documentable declaration
        (import/export/module/extern/static_assert) is released and reported.
        """
        block = self._take_doc()
        if block is None:
            return self._dispatch_toplevel_decl(p)
        before = [len(getattr(p, name)) for name in self.DOC_DECL_LISTS]
        self._dispatch_toplevel_decl(p)
        for i, name in enumerate(self.DOC_DECL_LISTS):
            decls = getattr(p, name)
            if len(decls) > before[i]:
                decls[-1].doc = block.text
                return
        self._release_doc(block)

    def _dispatch_toplevel_decl(self, p: Program):
        """Parse ONE top-level declaration at the current token and append it to
        the matching list of `p` (design 40 item 8 — the dispatch shared by the
        file-level `parse()` loop and inline-module bodies, so it lives in one
        place). Raises SyntaxError on a token that cannot begin a declaration;
        the caller owns loop control, the `EOF`/`RBRACE` terminator, and (in
        `parse()` only) the batched error recovery around each call.
        """
        # Attributes (design 58): zero or more `@name`/`@name("arg")` lines
        # immediately preceding a declaration. Legal on a top-level func/static
        # (`@export`, `@section`) and on an extension (`@synthesize`, design
        # 128); anything else is a clean "attributes are not supported" error
        # routed through `_parse_attributed_decl`.
        if self.match(TokenType.AT):
            attrs = self.parse_attributes()
            self.skip_newlines()
            return self._parse_attributed_decl(p, attrs)

        if self.match_ident("import"):
            p.imports.append(self.parse_import())
        elif self.match_ident("export"):
            p.exports.append(self.parse_export())
        elif self.match_ident("static_assert") and self.peek(1).type == TokenType.LPAREN:
            p.static_asserts.append(self.parse_static_assert())
        elif self.match(TokenType.PUBLIC):
            # Could be public module or public declaration
            if self.peek(1).type == TokenType.IDENT and self.peek(1).value == "module":
                p.module_decls.append(self.parse_module_decl())
            else:
                # Parse visibility and then the declaration
                visibility = self._parse_visibility()
                if self.match(TokenType.STRUCT):
                    p.structs.append(self.parse_struct(visibility))
                elif self.match(TokenType.ENUM):
                    p.enums.append(self.parse_enum(visibility))
                elif self.match(TokenType.TRAIT):
                    p.traits.append(self.parse_trait(visibility))
                elif self.match(TokenType.EXTENSION):
                    p.extensions.append(self.parse_extension(visibility))
                elif self.match(TokenType.FUNC):
                    p.functions.append(self.parse_function(visibility))
                elif self.match(TokenType.TYPE):
                    p.type_definitions.append(self.parse_type_definition(visibility))
                elif self.match(TokenType.STATIC):
                    p.statics.append(self.parse_static(visibility))
                else:
                    self.error(f"Expected struct, enum, trait, extension, func, type, or static after visibility modifier")
        elif self.match_ident("module"):
            p.module_decls.append(self.parse_module_decl())
        elif self.match(TokenType.STRUCT):
            p.structs.append(self.parse_struct())
        elif self.match(TokenType.ENUM):
            p.enums.append(self.parse_enum())
        elif self.match(TokenType.TRAIT):
            p.traits.append(self.parse_trait())
        elif self.match(TokenType.EXTENSION):
            p.extensions.append(self.parse_extension())
        elif self.match(TokenType.FUNC):
            p.functions.append(self.parse_function())
        elif self.match(TokenType.TYPE):
            p.type_definitions.append(self.parse_type_definition())
        elif self.match(TokenType.EXTERN):
            p.extern_blocks.append(self.parse_extern_block())
        elif self.match(TokenType.STATIC):
            p.statics.append(self.parse_static())
        else:
            self.error(f"Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got {self.current().type.name}")

    def _parse_attributed_decl(self, p: Program, attrs):
        """Parse the declaration following an attribute block and attach `attrs`.

        design 58: attributes are legal on a top-level `func`/`static`
        (`@export`, `@section`) and — since design 128 — on an `extension`
        (`@synthesize`), each optionally `public`-prefixed. Everything else gets
        a clean "attributes are not supported on X" error, and an attribute on
        the wrong one of the two gets the misplacement error below.
        """
        visibility = Visibility.PRIVATE
        if self.match(TokenType.PUBLIC):
            # `public module` is not an attributable declaration.
            if self.peek(1).type == TokenType.IDENT and self.peek(1).value == "module":
                self.error("attributes are not supported on module declarations")
            visibility = self._parse_visibility()

        if self.match(TokenType.FUNC):
            self._reject_misplaced_attributes(attrs, FUNC_STATIC_ATTRIBUTES,
                                              "function declarations")
            fn = self.parse_function(visibility)
            fn.attributes = attrs
            p.functions.append(fn)
        elif self.match(TokenType.STATIC):
            self._reject_misplaced_attributes(attrs, FUNC_STATIC_ATTRIBUTES,
                                              "static declarations")
            st = self.parse_static(visibility)
            st.attributes = attrs
            p.statics.append(st)
        elif self.match(TokenType.EXTENSION):
            self._reject_misplaced_attributes(attrs, EXTENSION_ATTRIBUTES,
                                              "extensions")
            ext = self.parse_extension(visibility)
            ext.attributes = attrs
            p.extensions.append(ext)
        else:
            self.error(f"attributes are not supported on {self._describe_decl_kind()}")

    def _reject_misplaced_attributes(self, attrs, allowed, where: str):
        """Error on any attribute in `attrs` that is not legal on `where`.

        Position is a grammar property, so it is enforced here rather than in
        the typechecker: `@export` belongs on a func/static, `@synthesize` on an
        extension, and each is a clean error on the other.
        """
        for attr in attrs:
            if attr.name not in allowed:
                legal = ", ".join("@" + a for a in allowed)
                self.error(f"attribute `@{attr.name}` is not supported on "
                           f"{where} (legal here: {legal})")

    def _describe_decl_kind(self) -> str:
        """Human phrase for the declaration at the current token (used in the
        'attributes are not supported on X' diagnostic)."""
        t = self.current()
        mapping = {
            TokenType.STRUCT: "struct declarations",
            TokenType.ENUM: "enum declarations",
            TokenType.TRAIT: "trait declarations",
            TokenType.TYPE: "type declarations",
            TokenType.EXTERN: "extern blocks",
        }
        if t.type in mapping:
            return mapping[t.type]
        if t.type == TokenType.IDENT and t.value in ("import", "module", "export"):
            return f"{t.value} declarations"
        return "this declaration"

    def parse(self) -> Program:
        program = Program(structs=[], functions=[])
        errors = []  # collected syntax error messages (batched recovery)
        self.skip_newlines()
        # `//!` module doc (design 121): legal only at the very top, so it is
        # claimed here, before the first declaration is parsed. A `//!` anywhere
        # else stays unclaimed and is reported by the sweep below.
        program.module_doc = self._take_module_docs()

        while not self.match(TokenType.EOF):
            try:
                self._parse_toplevel_decl(program)
            except SyntaxError as e:
                # Batch syntax errors: record this one, then synchronize to the
                # next top-level declaration and keep parsing so a single file
                # can report multiple independent errors in one run.
                errors.append(str(e))
                if len(errors) >= self.MAX_PARSE_ERRORS:
                    break
                self._synchronize()
            self.skip_newlines()

        # Doc comments never silently vanish: a block no declaration claimed is
        # reported alongside any syntax errors (design 121). Skipped when the
        # parse already failed, since recovery skips over declarations.
        if not errors:
            errors.extend(self._unattached_doc_errors())

        if errors:
            # Surface all collected errors. A single error reproduces the exact
            # prior message; multiple are joined so every one reaches the report.
            raise SyntaxError("\n".join(errors))

        return program

    def parse_import(self) -> ImportDecl:
        """Parse import declaration: import path.to.module or import path.{A, B}"""
        start = self.current()
        self.expect_ident("import")

        # Parse the module path
        path = []

        # First component: regular identifier or 'package'/'parent' for relative imports
        # Note: 'package' and 'parent' are NOT keywords to avoid conflicts with user code
        first = self.expect(TokenType.IDENT, "Expected module name after 'import'")
        path.append(first.value)

        # Parse remaining path segments
        while self.match(TokenType.DOT):
            self.advance()

            # Check for glob import: import foo.*
            if self.match(TokenType.STAR):
                self.advance()
                return ImportDecl(
                    path=path,
                    symbols=None,
                    alias=None,
                    is_glob=True,
                    line=start.line,
                    column=start.column
                )

            # Check for symbol set: import foo.{A, B as C} (design 53: per-symbol
            # `as` aliases).
            if self.match(TokenType.LBRACE):
                self.advance()
                symbols = []
                symbol_aliases = {}
                local_names = set()

                def parse_one_symbol():
                    sym = self.expect(TokenType.IDENT, "Expected symbol name in import")
                    symbols.append(sym.value)
                    local = sym.value
                    if self.match(TokenType.AS):
                        self.advance()
                        alias_tok = self.expect(TokenType.IDENT,
                                                "Expected alias name after 'as'")
                        symbol_aliases[sym.value] = alias_tok.value
                        local = alias_tok.value
                    # design 53: two entries of one selective import may not bind
                    # the same local name (an alias colliding with another
                    # imported name), reported with the offending local name.
                    if local in local_names:
                        self.error(f"imported name `{local}` is already bound by "
                                   f"this import")
                    local_names.add(local)

                if not self.match(TokenType.RBRACE):
                    parse_one_symbol()
                    while self.match(TokenType.COMMA):
                        self.advance()
                        if self.match(TokenType.RBRACE):
                            break
                        parse_one_symbol()
                self.expect(TokenType.RBRACE)
                return ImportDecl(
                    path=path,
                    symbols=symbols,
                    alias=None,
                    is_glob=False,
                    line=start.line,
                    column=start.column,
                    symbol_aliases=(symbol_aliases or None)
                )

            # Regular path component
            component = self.expect(TokenType.IDENT, "Expected module name after '.'")
            path.append(component.value)

        # Check for alias: import foo.bar as baz
        alias = None
        if self.match(TokenType.AS):
            self.advance()
            alias_token = self.expect(TokenType.IDENT, "Expected alias name after 'as'")
            alias = alias_token.value

        return ImportDecl(
            path=path,
            symbols=None,
            alias=alias,
            is_glob=False,
            line=start.line,
            column=start.column
        )

    def parse_static_assert(self):
        """Parse `static_assert(<const-expr>, "message")` (design 53). Legal at
        top level and in statement position. The message must be a plain string
        literal (it is baked into the compile-time diagnostic)."""
        from ast_nodes import StaticAssert
        start = self.current()
        self.advance()  # consume 'static_assert' identifier
        self.expect(TokenType.LPAREN, "Expected '(' after `static_assert`")
        condition = self.parse_expression()
        self.expect(TokenType.COMMA, "Expected ',' after the static_assert condition")
        msg_tok = self.expect(TokenType.STRING,
                              "static_assert message must be a plain string literal")
        self.expect(TokenType.RPAREN, "Expected ')' to close `static_assert`")
        return StaticAssert(
            condition=condition,
            message=msg_tok.value,
            line=start.line,
            column=start.column,
        )

    def parse_export(self) -> ExportDecl:
        """Parse export declaration for init.saw facades.

        Syntax:
        - export path.to.Symbol
        - export path.to.Symbol as AliasName
        - export path.to.*
        """
        start = self.current()
        self.expect_ident("export")

        # Parse the path
        path = []
        first = self.expect(TokenType.IDENT, "Expected path after 'export'")
        path.append(first.value)

        # Parse remaining path segments
        while self.match(TokenType.DOT):
            self.advance()

            # Check for glob export: export foo.*
            if self.match(TokenType.STAR):
                self.advance()
                return ExportDecl(
                    path=path,
                    alias=None,
                    is_glob=True,
                    line=start.line,
                    column=start.column
                )

            # Regular path component
            component = self.expect(TokenType.IDENT, "Expected name after '.'")
            path.append(component.value)

        # Check for alias: export foo.bar as baz
        alias = None
        if self.match(TokenType.AS):
            self.advance()
            alias_token = self.expect(TokenType.IDENT, "Expected alias name after 'as'")
            alias = alias_token.value

        return ExportDecl(
            path=path,
            alias=alias,
            is_glob=False,
            line=start.line,
            column=start.column
        )

    def parse_module_decl(self) -> ModuleDecl:
        """Parse module declaration: module name or public module name"""
        start = self.current()

        # Check for 'public' modifier
        is_public = False
        if self.match(TokenType.PUBLIC):
            is_public = True
            self.advance()

        self.expect_ident("module")
        name_token = self.expect(TokenType.IDENT, "Expected module name")

        # Check for inline module: module name { ... }
        is_inline = False
        body = None
        self.skip_newlines()
        if self.match(TokenType.LBRACE):
            is_inline = True
            self.advance()
            self.skip_newlines()
            # Parse the inline module body as a Program, reusing the shared
            # top-level dispatch (design 40 item 8). Inline modules do NOT run
            # batched error recovery — a syntax error here propagates to the
            # file-level `parse()` loop, which synchronizes past the whole
            # `module { ... }` — so the dispatch call is unguarded.
            body = Program(structs=[], functions=[])
            while not self.match(TokenType.RBRACE, TokenType.EOF):
                self._parse_toplevel_decl(body)
                self.skip_newlines()

            self.expect(TokenType.RBRACE)

        return ModuleDecl(
            name=name_token.value,
            is_public=is_public,
            is_inline=is_inline,
            body=body,
            line=start.line,
            column=start.column
        )
