"""
Saw Language Lexer
Tokenizes source code into a stream of tokens.
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import List, Optional
import re


class TokenType(Enum):
    # Literals
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    INTERP_STRING = auto()  # String with {expr} interpolation
    BOOL = auto()

    # Identifiers and keywords
    IDENT = auto()
    FUNC = auto()
    LET = auto()
    VAR = auto()
    IF = auto()
    ELSE = auto()
    GUARD = auto()
    RETURN = auto()
    TRUE = auto()
    FALSE = auto()
    STRUCT = auto()
    EXTENSION = auto()
    SELF = auto()
    INIT = auto()
    NONE = auto()
    ENUM = auto()
    CASE = auto()
    MATCH = auto()
    WHILE = auto()
    BREAK = auto()
    CONTINUE = auto()
    TRAIT = auto()
    FOR = auto()
    IN = auto()
    TYPE = auto()  # 'type' keyword for associated types
    EXTERN = auto()  # 'extern' for FFI declarations
    AS = auto()      # 'as' for type casting
    TRY = auto()     # 'try' for error handling
    CATCH = auto()   # 'catch' for error handling
    STATIC = auto()  # 'static' for module-level static declarations (design 41)

    # Module system keywords
    MODULE = auto()   # 'module' for module declarations
    IMPORT = auto()   # 'import' for imports
    PUBLIC = auto()   # 'public' visibility modifier
    EXPORT = auto()   # 'export' for init.saw re-exports
    PACKAGE = auto()  # 'package' for package-relative imports
    PARENT = auto()   # 'parent' for parent-relative imports

    # Note: Type names (Int, String, Bool, etc.) are NOT special tokens.
    # They are lexed as IDENT and recognized by the typechecker.
    # This simplifies the parser and allows them to be used in generic contexts.

    # Operators
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()        # % for modulo
    EQ = auto()
    NEQ = auto()
    LT = auto()
    GT = auto()
    LTE = auto()
    GTE = auto()
    AND = auto()            # && for logical and
    OR = auto()             # || for logical or
    AMPERSAND = auto()      # & for references / binary bitwise AND
    PIPE = auto()           # | binary bitwise OR
    CARET = auto()          # ^ binary bitwise XOR
    TILDE = auto()          # ~ unary bitwise complement
    WRAP_ADD = auto()       # &+ wrapping (two's-complement) addition
    WRAP_SUB = auto()       # &- wrapping (two's-complement) subtraction
    WRAP_MUL = auto()       # &* wrapping (two's-complement) multiplication
    NOT = auto()            # 'not' keyword for logical not
    MOVE = auto()           # 'move' keyword for ownership transfer
    UNSAFE = auto()         # 'unsafe' effect-slot marker (designs 130/136)
    BORROWS = auto()        # 'borrows' effect-slot marker (design 141)
    LEND = auto()           # 'lend' body statement (design 141)
    ASSIGN = auto()
    PLUS_ASSIGN = auto()    # += compound assignment
    MINUS_ASSIGN = auto()   # -= compound assignment
    STAR_ASSIGN = auto()    # *= compound assignment
    SLASH_ASSIGN = auto()   # /= compound assignment
    PERCENT_ASSIGN = auto() # %= compound assignment
    AMP_ASSIGN = auto()     # &= bitwise-AND compound assignment
    PIPE_ASSIGN = auto()    # |= bitwise-OR compound assignment
    CARET_ASSIGN = auto()   # ^= bitwise-XOR compound assignment
    SHL_ASSIGN = auto()     # <<= shift-left compound assignment
    SHR_ASSIGN = auto()     # >>= shift-right compound assignment
    QUESTION = auto()       # ? for optional types
    DOUBLE_QUESTION = auto() # ?? for nil coalescing
    EXCLAIM = auto()        # ! for force unwrap
    QUESTION_DOT = auto()   # ?. for optional chaining
    DOTDOT = auto()         # .. for ranges (exclusive)
    DOTDOT_EQ = auto()      # ..= for inclusive ranges (design 53)
    ELLIPSIS = auto()       # ... for variadic functions

    # Delimiters
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()       # [ for arrays
    RBRACKET = auto()       # ] for arrays
    COMMA = auto()
    COLON = auto()
    SEMICOLON = auto()      # ; for array type syntax [T; N]
    ARROW = auto()
    DOT = auto()

    # Attributes (design 58)
    AT = auto()             # @ for attributes: @export, @section(...)

    # Source-location magic literals (design 98): #file / #line / #function.
    # The token value is the bare directive name ('file'|'line'|'function').
    HASH_DIRECTIVE = auto()

    # Closure parameters
    DOLLAR_PARAM = auto()   # $0, $1, etc. for shorthand closures

    # Special
    NEWLINE = auto()
    EOF = auto()


@dataclass
class Token:
    type: TokenType
    value: str
    line: int
    column: int
    # Integer-literal suffix (design 53): one of i8/i16/i32/i64/u8/u16/u32/u64
    # when the literal was written `255u8` / `0xFF_u8`; otherwise None.
    suffix: Optional[str] = None


@dataclass
class DocComment:
    """A captured documentation comment LINE (design 121).

    Doc comments are lexed as TRIVIA — they never enter the token stream (the
    default dump stays byte-identical), they are recorded out-of-band here. A
    `///` line is `kind='doc'` and documents the following declaration; a `//!`
    line is `kind='module'` and documents the enclosing module. `text` is the
    line body with the `///`/`//!` prefix (and exactly one following space, if
    present) stripped. `line`/`column` are 1-based at the leading `/`. The
    parser groups contiguous same-kind lines into blocks and attaches them.
    """
    kind: str          # 'doc' or 'module'
    text: str
    line: int
    column: int


KEYWORDS = {
    'func': TokenType.FUNC,
    'let': TokenType.LET,
    'var': TokenType.VAR,
    'if': TokenType.IF,
    'else': TokenType.ELSE,
    'guard': TokenType.GUARD,
    'return': TokenType.RETURN,
    'true': TokenType.TRUE,
    'false': TokenType.FALSE,
    'struct': TokenType.STRUCT,
    'extension': TokenType.EXTENSION,
    'self': TokenType.SELF,
    'init': TokenType.INIT,
    'None': TokenType.NONE,
    'enum': TokenType.ENUM,
    'while': TokenType.WHILE,
    'break': TokenType.BREAK,
    'continue': TokenType.CONTINUE,
    'case': TokenType.CASE,
    'match': TokenType.MATCH,
    'trait': TokenType.TRAIT,
    'for': TokenType.FOR,
    'in': TokenType.IN,
    'type': TokenType.TYPE,
    'extern': TokenType.EXTERN,
    'not': TokenType.NOT,
    'move': TokenType.MOVE,
    'unsafe': TokenType.UNSAFE,
    # design 141. `borrows` fills the effect slot (`func [](i: Int) borrows -> T`)
    # and `lend` marks the borrow window in the body. Unlike `sync`/`escaping`,
    # which stay contextual identifiers, both are RESERVED: `lend` opens a
    # statement, where a contextual read would collide with a call to a function
    # named `lend`, and `borrows` is reserved with it so the pair reads as one
    # feature. Neither name appears as an identifier anywhere in the corpus.
    'borrows': TokenType.BORROWS,
    'lend': TokenType.LEND,
    'as': TokenType.AS,
    'try': TokenType.TRY,
    'catch': TokenType.CATCH,
    'static': TokenType.STATIC,
    # Module system
    # Note: 'module', 'import', and 'export' are NOT keywords - they are handled
    # specially by the parser only in specific syntactic positions to avoid
    # conflicts with user code (like 'package' and 'parent').
    'public': TokenType.PUBLIC,
    # Note: 'package' and 'parent' are NOT keywords - they are handled
    # specially by the parser only in import contexts to avoid conflicts
    # with user code (e.g., a method named 'parent')
    #
    # Note: Type names (Int, Float, Bool, String, Int8, UInt64, etc.) are NOT
    # keywords. They are lexed as IDENT and recognized by the typechecker.
    # This simplifies the parser and enables generic specialization syntax
    # like `extension Vector<String>`.
}


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []
        # Doc-comment trivia (design 121), captured in source order. Out of band:
        # never enters `self.tokens`, so the token stream is unchanged.
        self.doc_comments: List[DocComment] = []

    def error(self, msg: str):
        raise SyntaxError(f"Lexer error at {self.line}:{self.column}: {msg}")

    def peek(self, offset: int = 0) -> Optional[str]:
        pos = self.pos + offset
        if pos < len(self.source):
            return self.source[pos]
        return None

    def advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == '\n':
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def skip_whitespace(self):
        while self.peek() and self.peek() in ' \t\r':
            self.advance()

    def _at_line_start(self) -> bool:
        """True if only whitespace precedes the current position on this line —
        i.e. the token/comment about to be read is the first thing on its line.
        Doc comments (`///`/`//!`) are recognized only at line start; a `///`
        trailing live code is an ordinary comment (design 121)."""
        i = self.pos - 1
        while i >= 0:
            c = self.source[i]
            if c == '\n':
                return True
            if c not in ' \t\r':
                return False
            i -= 1
        return True

    def skip_comment(self):
        if self.peek() == '/' and self.peek(1) == '/':
            # Design 121 doc-comment trivia. A line-leading `///` (exactly three
            # slashes) is a doc comment; a line-leading `//!` is a module-doc
            # comment. `////` (4+) and any comment trailing live code is ordinary.
            third = self.peek(2)
            at_start = self._at_line_start()
            is_doc = at_start and third == '/' and self.peek(3) != '/'
            is_module = at_start and third == '!'
            if is_doc or is_module:
                start_line, start_col = self.line, self.column
                self.advance(); self.advance(); self.advance()  # '///' or '//!'
                # Strip exactly one leading space, if present.
                if self.peek() == ' ':
                    self.advance()
                chars = []
                while self.peek() is not None and self.peek() != '\n':
                    chars.append(self.advance())
                text = ''.join(chars)
                if text.endswith('\r'):
                    text = text[:-1]
                self.doc_comments.append(DocComment(
                    kind='module' if is_module else 'doc',
                    text=text, line=start_line, column=start_col))
                return
            while self.peek() and self.peek() != '\n':
                self.advance()

    def _read_unicode_escape(self) -> str:
        """Read the tail of a `\\u{XXXX}` escape (the `\\u` is already consumed),
        design 53. 1–6 hex digits naming a valid Unicode scalar; surrogates
        (D800–DFFF) and code points > 0x10FFFF are rejected at lex time so string
        literals stay always-valid UTF-8. Returns the scalar's character (encoded
        to UTF-8 bytes when the literal's value is emitted)."""
        if self.peek() != '{':
            self.error("expected `{` after `\\u` in a Unicode escape "
                       "(write `\\u{1F600}`)")
        self.advance()  # consume '{'
        digits = []
        while self.peek() is not None and self.peek() != '}':
            digits.append(self.advance())
        if self.peek() != '}':
            self.error("unterminated `\\u{...}` escape")
        self.advance()  # consume '}'
        hex_str = ''.join(digits)
        if not (1 <= len(hex_str) <= 6) or any(
                c not in '0123456789abcdefABCDEF' for c in hex_str):
            self.error(f"`\\u{{{hex_str}}}` must contain 1–6 hexadecimal digits")
        cp = int(hex_str, 16)
        if cp > 0x10FFFF:
            self.error(f"`\\u{{{hex_str}}}` is greater than the maximum Unicode "
                       f"scalar 0x10FFFF")
        if 0xD800 <= cp <= 0xDFFF:
            self.error(f"`\\u{{{hex_str}}}` is a surrogate code point, which is "
                       f"not a valid Unicode scalar")
        return chr(cp)

    def read_string(self) -> tuple:
        """Read a string literal, detecting interpolation markers.

        Returns: (string_value, has_interpolation)
        - For plain strings: ("hello", False)
        - For interpolated: ("hello {name}!", True) - braces preserved
        """
        self.advance()  # consume opening quote
        result = []
        has_interpolation = False
        # Position of the FIRST interpolation `{` opened in this literal (None =
        # none yet). An unbalanced interpolation reports HERE, not at EOF (DF-116d):
        # a stray `{` otherwise runs the scan off the end of the file and surfaces
        # as a far-away "Unterminated string".
        interp_open = None

        while self.peek() and self.peek() != '"':
            if self.peek() == '\\':
                self.advance()
                ch = self.advance()
                # The supported escape set is EXACTLY: \\ \" \n \t \r \0 \u{...}
                # plus the \{ \} brace forms. Any other sequence is a clean lex
                # error — never a silent backslash-drop (which used to turn
                # `"\r\n"` into `"r\n"`).
                if ch == 'n':
                    result.append('\n')
                elif ch == 't':
                    result.append('\t')
                elif ch == 'r':
                    result.append('\r')          # carriage return (13)
                elif ch == '0':
                    result.append('\x00')        # NUL (0); interior NULs are
                                                 # representable (String design)
                elif ch == '"':
                    result.append('"')
                elif ch == '\\':
                    result.append('\\')
                elif ch == '{':
                    result.append('\x01{')  # Escaped brace - use marker to distinguish from interpolation
                elif ch == '}':
                    result.append('\x01}')  # Escaped brace - use marker to distinguish from interpolation
                elif ch == 'u':
                    result.append(self._read_unicode_escape())
                else:
                    self.error(f"unknown escape `\\{ch}` in a string literal "
                               f"(supported: \\\\ \\\" \\n \\t \\r \\0 \\u{{...}})")
            elif self.peek() == '{':
                # Interpolation detected - preserve braces for parser
                has_interpolation = True
                open_line, open_col = self.line, self.column
                if interp_open is None:
                    interp_open = (open_line, open_col)
                result.append(self.advance())  # Keep {
                # Read until matching }, tracking nested braces
                brace_depth = 1
                while self.peek() and brace_depth > 0:
                    ch = self.peek()
                    if ch == '{':
                        brace_depth += 1
                    elif ch == '}':
                        brace_depth -= 1
                    result.append(self.advance())
                if brace_depth > 0:
                    # This interpolation ran to EOF without a closing `}`.
                    raise SyntaxError(
                        "Lexer error at %d:%d: unterminated interpolation in "
                        "string literal, opened at this `{` (write `\\{` for a "
                        "literal brace)" % (open_line, open_col))
            else:
                result.append(self.advance())

        if not self.peek():
            # At EOF with the string still open. If an interpolation `{` was
            # opened, the likely cause is a stray brace meant as a literal: point
            # at that brace (its `}` was probably consumed by a later `}`) rather
            # than at the far-off EOF.
            if interp_open is not None:
                il, ic = interp_open
                raise SyntaxError(
                    "Lexer error at %d:%d: unterminated interpolation in string "
                    "literal, opened at this `{` (write `\\{` for a literal "
                    "brace)" % (il, ic))
            self.error("Unterminated string")
        self.advance()  # consume closing quote
        return (''.join(result), has_interpolation)

    # Without design 47, `Int`/`UInt` are 64-bit, so an integer literal must be
    # representable in 64 bits — as a signed OR unsigned value (literals are
    # non-negative; unary minus is a separate operator). The widest legal literal
    # is UInt64.max = 2**64 - 1; anything larger is a compile error at the literal.
    INT_LITERAL_MAX = (1 << 64) - 1

    def _check_int_range(self, value: int, start_col: int):
        if value > self.INT_LITERAL_MAX:
            raise SyntaxError(
                f"Lexer error at {self.line}:{start_col}: integer literal {value} "
                f"is out of range for a 64-bit integer "
                f"(max {self.INT_LITERAL_MAX})"
            )

    # Design 53 literal suffixes: each maps to its bit width. A suffixed literal
    # IS that fixed-width type, range-checked at the literal (`256u8` errors).
    INT_SUFFIX_WIDTHS = {
        'i8': 8, 'i16': 16, 'i32': 32, 'i64': 64,
        'u8': 8, 'u16': 16, 'u32': 32, 'u64': 64,
    }

    def _try_read_int_suffix(self):
        """Positioned just after an integer literal's digits (underscores already
        consumed), tentatively read a fixed-width suffix (design 53). Returns the
        suffix string (e.g. `u8`) and consumes it, or returns None and consumes
        nothing when the following characters are not a clean suffix (so `5abc`
        stays INT + IDENT and `0xFace` reads as hex)."""
        ch = self.peek()
        if ch not in ('i', 'u'):
            return None
        j = self.pos + 1
        digits = []
        while j < len(self.source) and self.source[j].isdigit():
            digits.append(self.source[j])
            j += 1
        cand = ch + ''.join(digits)
        if cand not in self.INT_SUFFIX_WIDTHS:
            return None
        # A trailing identifier character means this wasn't a bare suffix.
        if j < len(self.source) and (self.source[j].isalnum() or self.source[j] == '_'):
            return None
        for _ in range(len(cand)):
            self.advance()
        return cand

    def _check_suffixed_range(self, value: int, suffix: str, start_col: int):
        width = self.INT_SUFFIX_WIDTHS[suffix]
        # A literal is non-negative (unary minus is a separate operator); it is
        # legal iff its bit pattern fits the width (0 .. 2**width - 1), matching
        # the platform-Int rule (signed low bound through unsigned high bound).
        if value > (1 << width) - 1:
            raise SyntaxError(
                f"Lexer error at {self.line}:{start_col}: integer literal "
                f"{value}{suffix} is out of range for `{suffix}` "
                f"(max {(1 << width) - 1})"
            )

    def read_number(self) -> Token:
        start_col = self.column

        # Based integer literals: 0x.. (hex), 0b.. (binary), 0o.. (octal).
        # Underscores may separate digits (`0xDEAD_BEEF`). The canonical token
        # value keeps the prefix and strips underscores so the parser can decode
        # it with the matching base.
        nxt = self.peek(1)
        if self.peek() == '0' and nxt is not None and nxt in 'xXbBoO':
            prefix = nxt.lower()
            self.advance()  # '0'
            self.advance()  # base char
            digit_sets = {'x': '0123456789abcdefABCDEF_', 'b': '01_', 'o': '01234567_'}
            allowed = digit_sets[prefix]
            digits = []
            while self.peek() is not None and self.peek() in allowed:
                digits.append(self.advance())
            digit_str = ''.join(digits).replace('_', '')
            if not digit_str:
                self.error(f"integer literal has no digits after '0{prefix}'")
            base = {'x': 16, 'b': 2, 'o': 8}[prefix]
            value = int(digit_str, base)
            suffix = self._try_read_int_suffix()
            if suffix is not None:
                self._check_suffixed_range(value, suffix, start_col)
            else:
                self._check_int_range(value, start_col)
            return Token(TokenType.INT, '0' + prefix + digit_str, self.line,
                         start_col, suffix=suffix)

        # Decimal integer or float, with underscore digit separators (`1_000_000`).
        result = []
        is_float = False
        while self.peek() and (self.peek().isdigit() or self.peek() == '.' or self.peek() == '_'):
            if self.peek() == '.':
                # Check if this is a range operator (..) - don't consume the dot
                if self.peek(1) == '.':
                    break
                if is_float:
                    break
                is_float = True
            result.append(self.advance())

        value = ''.join(result).replace('_', '')
        if is_float:
            # Float literals take no integer suffix (design 53).
            return Token(TokenType.FLOAT, value, self.line, start_col)
        ival = int(value)
        suffix = self._try_read_int_suffix()
        if suffix is not None:
            self._check_suffixed_range(ival, suffix, start_col)
        else:
            self._check_int_range(ival, start_col)
        return Token(TokenType.INT, value, self.line, start_col, suffix=suffix)

    # Source-location magic literals (design 98): the ONLY `#` directives.
    HASH_DIRECTIVES = {'file', 'line', 'function'}

    def read_hash_directive(self) -> Token:
        """Lex a `#file` / `#line` / `#function` source-location literal (design
        98). `#` is otherwise unused at the token level. An unrecognized
        `#foo` is a clean "unknown directive" lex error (never silently
        consumed)."""
        start_col = self.column
        self.advance()  # consume '#'
        name_chars = []
        while self.peek() and (self.peek().isalnum() or self.peek() == '_'):
            name_chars.append(self.advance())
        name = ''.join(name_chars)
        if not name:
            raise SyntaxError(
                f"Lexer error at {self.line}:{start_col}: expected a directive "
                f"name after `#` (one of #file, #line, #function)")
        if name not in self.HASH_DIRECTIVES:
            raise SyntaxError(
                f"Lexer error at {self.line}:{start_col}: unknown directive "
                f"`#{name}` (expected one of #file, #line, #function)")
        return Token(TokenType.HASH_DIRECTIVE, name, self.line, start_col)

    def read_identifier(self) -> Token:
        start_col = self.column
        result = []

        while self.peek() and (self.peek().isalnum() or self.peek() == '_'):
            result.append(self.advance())

        value = ''.join(result)
        token_type = KEYWORDS.get(value, TokenType.IDENT)
        return Token(token_type, value, self.line, start_col)

    def add_token(self, token_type: TokenType, value: str = None):
        if value is None:
            value = token_type.name.lower()
        self.tokens.append(Token(token_type, value, self.line, self.column))

    def tokenize(self) -> List[Token]:
        while self.pos < len(self.source):
            self.skip_whitespace()
            self.skip_comment()

            if self.pos >= len(self.source):
                break

            ch = self.peek()

            if ch == '\n':
                self.add_token(TokenType.NEWLINE, '\n')
                self.advance()
            elif ch == '"':
                # DF-116e: capture the START line too — read_string advances
                # self.line over a multi-line interpolation, and a token's line
                # is its start (the spec's #line rule; the design-116 Saw port
                # agrees).
                start_line = self.line
                start_col = self.column
                value, has_interpolation = self.read_string()
                token_type = TokenType.INTERP_STRING if has_interpolation else TokenType.STRING
                self.tokens.append(Token(token_type, value, start_line, start_col))
            elif ch.isdigit():
                self.tokens.append(self.read_number())
            elif ch.isalpha() or ch == '_':
                self.tokens.append(self.read_identifier())
            elif ch == '+':
                if self.peek(1) == '=':
                    self.add_token(TokenType.PLUS_ASSIGN, '+=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.PLUS, '+')
                    self.advance()
            elif ch == '-':
                if self.peek(1) == '>':
                    self.add_token(TokenType.ARROW, '->')
                    self.advance()
                    self.advance()
                elif self.peek(1) == '=':
                    self.add_token(TokenType.MINUS_ASSIGN, '-=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.MINUS, '-')
                    self.advance()
            elif ch == '*':
                if self.peek(1) == '=':
                    self.add_token(TokenType.STAR_ASSIGN, '*=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.STAR, '*')
                    self.advance()
            elif ch == '/':
                if self.peek(1) == '/':
                    self.skip_comment()
                elif self.peek(1) == '=':
                    self.add_token(TokenType.SLASH_ASSIGN, '/=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.SLASH, '/')
                    self.advance()
            elif ch == '%':
                if self.peek(1) == '=':
                    self.add_token(TokenType.PERCENT_ASSIGN, '%=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.PERCENT, '%')
                    self.advance()
            elif ch == '&':
                if self.peek(1) == '&':
                    self.add_token(TokenType.AND, '&&')
                    self.advance()
                    self.advance()
                elif self.peek(1) == '+':
                    # Wrapping add: single token, no interior whitespace. Distinct
                    # from a call-site reference `&x` (a prefix position) and from
                    # a bare `&`, which stays AMPERSAND.
                    self.add_token(TokenType.WRAP_ADD, '&+')
                    self.advance()
                    self.advance()
                elif self.peek(1) == '-':
                    self.add_token(TokenType.WRAP_SUB, '&-')
                    self.advance()
                    self.advance()
                elif self.peek(1) == '*':
                    self.add_token(TokenType.WRAP_MUL, '&*')
                    self.advance()
                    self.advance()
                elif self.peek(1) == '=':
                    # &= bitwise-AND compound assignment (design 50). Distinct
                    # from `&&`, `&+/-/*`, and a bare `&`.
                    self.add_token(TokenType.AMP_ASSIGN, '&=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.AMPERSAND, '&')
                    self.advance()
            elif ch == '|':
                if self.peek(1) == '|':
                    self.add_token(TokenType.OR, '||')
                    self.advance()
                    self.advance()
                elif self.peek(1) == '=':
                    self.add_token(TokenType.PIPE_ASSIGN, '|=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.PIPE, '|')
                    self.advance()
            elif ch == '^':
                if self.peek(1) == '=':
                    self.add_token(TokenType.CARET_ASSIGN, '^=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.CARET, '^')
                    self.advance()
            elif ch == '~':
                self.add_token(TokenType.TILDE, '~')
                self.advance()
            elif ch == '=':
                if self.peek(1) == '=':
                    self.add_token(TokenType.EQ, '==')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.ASSIGN, '=')
                    self.advance()
            elif ch == '!':
                if self.peek(1) == '=':
                    self.add_token(TokenType.NEQ, '!=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.EXCLAIM, '!')
                    self.advance()
            elif ch == '?':
                if self.peek(1) == '?':
                    self.add_token(TokenType.DOUBLE_QUESTION, '??')
                    self.advance()
                    self.advance()
                elif self.peek(1) == '.':
                    self.add_token(TokenType.QUESTION_DOT, '?.')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.QUESTION, '?')
                    self.advance()
            elif ch == '<':
                # `<<=` is a single compound-assign token (design 50). Bare `<<`
                # is intentionally left as two `<` tokens so nested generic
                # closings like `Vector<Box<Int>>` are unaffected; the parser
                # combines two adjacent `<`/`>` into a shift only in expression
                # position (see parse_shift).
                if self.peek(1) == '<' and self.peek(2) == '=':
                    self.add_token(TokenType.SHL_ASSIGN, '<<=')
                    self.advance()
                    self.advance()
                    self.advance()
                elif self.peek(1) == '=':
                    self.add_token(TokenType.LTE, '<=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.LT, '<')
                    self.advance()
            elif ch == '>':
                if self.peek(1) == '>' and self.peek(2) == '=':
                    self.add_token(TokenType.SHR_ASSIGN, '>>=')
                    self.advance()
                    self.advance()
                    self.advance()
                elif self.peek(1) == '=':
                    self.add_token(TokenType.GTE, '>=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.GT, '>')
                    self.advance()
            elif ch == '(':
                self.add_token(TokenType.LPAREN, '(')
                self.advance()
            elif ch == ')':
                self.add_token(TokenType.RPAREN, ')')
                self.advance()
            elif ch == '{':
                self.add_token(TokenType.LBRACE, '{')
                self.advance()
            elif ch == '}':
                self.add_token(TokenType.RBRACE, '}')
                self.advance()
            elif ch == '[':
                self.add_token(TokenType.LBRACKET, '[')
                self.advance()
            elif ch == ']':
                self.add_token(TokenType.RBRACKET, ']')
                self.advance()
            elif ch == ';':
                self.add_token(TokenType.SEMICOLON, ';')
                self.advance()
            elif ch == ',':
                self.add_token(TokenType.COMMA, ',')
                self.advance()
            elif ch == ':':
                self.add_token(TokenType.COLON, ':')
                self.advance()
            elif ch == '.':
                if self.peek(1) == '.' and self.peek(2) == '.':
                    self.add_token(TokenType.ELLIPSIS, '...')
                    self.advance()
                    self.advance()
                    self.advance()
                elif self.peek(1) == '.' and self.peek(2) == '=':
                    # `..=` inclusive range (design 53). Checked before bare `..`
                    # so `0..=5` is one token, leaving `0..5` unaffected.
                    self.add_token(TokenType.DOTDOT_EQ, '..=')
                    self.advance()
                    self.advance()
                    self.advance()
                elif self.peek(1) == '.':
                    self.add_token(TokenType.DOTDOT, '..')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.DOT, '.')
                    self.advance()
            elif ch == '@':
                self.add_token(TokenType.AT, '@')
                self.advance()
            elif ch == '#':
                self.tokens.append(self.read_hash_directive())
            elif ch == '$':
                start_col = self.column
                self.advance()  # consume '$'
                if self.peek() and self.peek().isdigit():
                    num = []
                    while self.peek() and self.peek().isdigit():
                        num.append(self.advance())
                    value = '$' + ''.join(num)
                    self.tokens.append(Token(TokenType.DOLLAR_PARAM, value, self.line, start_col))
                else:
                    self.error("Expected number after '$' for shorthand closure parameter")
            else:
                self.error(f"Unexpected character: {ch}")

        self.tokens.append(Token(TokenType.EOF, '', self.line, self.column))
        return self.tokens
