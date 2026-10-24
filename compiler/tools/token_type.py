"""The frozen parser's token kinds, which `sawc_reading` maps sawc's tokens onto.

The members, and their order, are v0.18.0's `sawc/lexer.py` `TokenType`: the
subset checker's rules and the parser's lanes are written over the frozen
parser's tree and tokens, so the vocabulary is kept as that tree knows it.
"""
from enum import Enum, auto


class TokenType(Enum):
    # Literals
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    INTERP_STRING = auto()
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
    TYPE = auto()    # nothing produces it: `type` is contextual and lexes as IDENT
    EXTERN = auto()
    AS = auto()
    TRY = auto()
    CATCH = auto()
    STATIC = auto()

    # Module system keywords
    MODULE = auto()
    IMPORT = auto()
    PUBLIC = auto()
    EXPORT = auto()
    PACKAGE = auto()
    PARENT = auto()

    # Operators
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    EQ = auto()
    NEQ = auto()
    LT = auto()
    GT = auto()
    LTE = auto()
    GTE = auto()
    AND = auto()
    OR = auto()
    AMPERSAND = auto()
    PIPE = auto()
    CARET = auto()
    TILDE = auto()
    WRAP_ADD = auto()
    WRAP_SUB = auto()
    WRAP_MUL = auto()
    NOT = auto()
    MOVE = auto()
    UNSAFE = auto()
    BORROWS = auto()
    LEND = auto()
    ASSIGN = auto()
    PLUS_ASSIGN = auto()
    MINUS_ASSIGN = auto()
    STAR_ASSIGN = auto()
    SLASH_ASSIGN = auto()
    PERCENT_ASSIGN = auto()
    AMP_ASSIGN = auto()
    PIPE_ASSIGN = auto()
    CARET_ASSIGN = auto()
    SHL_ASSIGN = auto()
    SHR_ASSIGN = auto()
    QUESTION = auto()
    DOUBLE_QUESTION = auto()
    EXCLAIM = auto()
    QUESTION_DOT = auto()
    DOTDOT = auto()
    DOTDOT_EQ = auto()
    ELLIPSIS = auto()

    # Delimiters
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    COMMA = auto()
    COLON = auto()
    SEMICOLON = auto()
    ARROW = auto()
    DOT = auto()

    # Attributes
    AT = auto()

    # Source-location literals: #file, #line, #function, the value the bare name
    HASH_DIRECTIVE = auto()

    # Shorthand closure parameters ($0, $1, ...)
    DOLLAR_PARAM = auto()

    # Special
    NEWLINE = auto()
    EOF = auto()
