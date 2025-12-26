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
    INTERFACE = auto()
    FOR = auto()
    IN = auto()
    TYPE = auto()  # 'type' keyword for associated types

    # Types
    INT_TYPE = auto()
    FLOAT_TYPE = auto()
    BOOL_TYPE = auto()
    STRING_TYPE = auto()

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
    NOT = auto()            # 'not' keyword for logical not
    MOVE = auto()           # 'move' keyword for ownership transfer
    ASSIGN = auto()
    QUESTION = auto()       # ? for optional types
    DOUBLE_QUESTION = auto() # ?? for nil coalescing
    EXCLAIM = auto()        # ! for force unwrap
    QUESTION_DOT = auto()   # ?. for optional chaining
    DOTDOT = auto()         # .. for ranges

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
    'interface': TokenType.INTERFACE,
    'for': TokenType.FOR,
    'in': TokenType.IN,
    'type': TokenType.TYPE,
    'not': TokenType.NOT,
    'move': TokenType.MOVE,
    'Int': TokenType.INT_TYPE,
    'Float': TokenType.FLOAT_TYPE,
    'Bool': TokenType.BOOL_TYPE,
    'String': TokenType.STRING_TYPE,
}


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []

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

    def skip_comment(self):
        if self.peek() == '/' and self.peek(1) == '/':
            while self.peek() and self.peek() != '\n':
                self.advance()

    def read_string(self) -> str:
        self.advance()  # consume opening quote
        result = []
        while self.peek() and self.peek() != '"':
            if self.peek() == '\\':
                self.advance()
                ch = self.advance()
                if ch == 'n':
                    result.append('\n')
                elif ch == 't':
                    result.append('\t')
                elif ch == '"':
                    result.append('"')
                elif ch == '\\':
                    result.append('\\')
                else:
                    result.append(ch)
            else:
                result.append(self.advance())
        if not self.peek():
            self.error("Unterminated string")
        self.advance()  # consume closing quote
        return ''.join(result)

    def read_number(self) -> Token:
        start_col = self.column
        result = []
        is_float = False

        while self.peek() and (self.peek().isdigit() or self.peek() == '.'):
            if self.peek() == '.':
                # Check if this is a range operator (..) - don't consume the dot
                if self.peek(1) == '.':
                    break
                if is_float:
                    break
                is_float = True
            result.append(self.advance())

        value = ''.join(result)
        token_type = TokenType.FLOAT if is_float else TokenType.INT
        return Token(token_type, value, self.line, start_col)

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
                start_col = self.column
                value = self.read_string()
                self.tokens.append(Token(TokenType.STRING, value, self.line, start_col))
            elif ch.isdigit():
                self.tokens.append(self.read_number())
            elif ch.isalpha() or ch == '_':
                self.tokens.append(self.read_identifier())
            elif ch == '+':
                self.add_token(TokenType.PLUS, '+')
                self.advance()
            elif ch == '-':
                if self.peek(1) == '>':
                    self.add_token(TokenType.ARROW, '->')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.MINUS, '-')
                    self.advance()
            elif ch == '*':
                self.add_token(TokenType.STAR, '*')
                self.advance()
            elif ch == '/':
                if self.peek(1) == '/':
                    self.skip_comment()
                else:
                    self.add_token(TokenType.SLASH, '/')
                    self.advance()
            elif ch == '%':
                self.add_token(TokenType.PERCENT, '%')
                self.advance()
            elif ch == '&':
                if self.peek(1) == '&':
                    self.add_token(TokenType.AND, '&&')
                    self.advance()
                    self.advance()
                else:
                    self.error(f"Unexpected character: {ch} (did you mean '&&'?)")
            elif ch == '|':
                if self.peek(1) == '|':
                    self.add_token(TokenType.OR, '||')
                    self.advance()
                    self.advance()
                else:
                    self.error(f"Unexpected character: {ch} (did you mean '||'?)")
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
                if self.peek(1) == '=':
                    self.add_token(TokenType.LTE, '<=')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.LT, '<')
                    self.advance()
            elif ch == '>':
                if self.peek(1) == '=':
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
                if self.peek(1) == '.':
                    self.add_token(TokenType.DOTDOT, '..')
                    self.advance()
                    self.advance()
                else:
                    self.add_token(TokenType.DOT, '.')
                    self.advance()
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
