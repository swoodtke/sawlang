"""
Saw Language Error Reporting
Provides nice error messages with source locations and context.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional


class ErrorKind(Enum):
    # Syntax errors
    SYNTAX = auto()

    # Type errors
    TYPE_MISMATCH = auto()
    UNKNOWN_TYPE = auto()

    # Semantic errors
    UNDEFINED_VARIABLE = auto()
    UNDEFINED_FUNCTION = auto()
    DUPLICATE_VARIABLE = auto()
    DUPLICATE_FUNCTION = auto()
    WRONG_ARGUMENT_COUNT = auto()
    IMMUTABLE_ASSIGNMENT = auto()
    INVALID_BREAK_CONTINUE = auto()

    # Warnings
    UNUSED_VARIABLE = auto()


@dataclass
class SourceLocation:
    line: int
    column: int
    filename: str = "<input>"


@dataclass
class CompilerError:
    kind: ErrorKind
    message: str
    location: SourceLocation
    hint: Optional[str] = None
    is_warning: bool = False


class ErrorReporter:
    """Collects and formats compiler errors."""

    def __init__(self, source: str, filename: str = "<input>"):
        self.source = source
        self.source_lines = source.split('\n')
        self.filename = filename
        self.errors: List[CompilerError] = []
        self.warnings: List[CompilerError] = []

    def error(self, kind: ErrorKind, message: str, line: int, column: int,
              hint: Optional[str] = None):
        """Report an error."""
        loc = SourceLocation(line, column, self.filename)
        err = CompilerError(kind, message, loc, hint, is_warning=False)
        self.errors.append(err)

    def warning(self, kind: ErrorKind, message: str, line: int, column: int,
                hint: Optional[str] = None):
        """Report a warning."""
        loc = SourceLocation(line, column, self.filename)
        warn = CompilerError(kind, message, loc, hint, is_warning=True)
        self.warnings.append(warn)

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def format_error(self, err: CompilerError) -> str:
        """Format a single error with source context."""
        lines = []

        # Error header
        kind = "warning" if err.is_warning else "error"
        lines.append(f"\033[1;31m{kind}\033[0m: {err.message}")

        # Location
        lines.append(f"  \033[1;34m-->\033[0m {err.location.filename}:{err.location.line}:{err.location.column}")

        # Source context
        if 1 <= err.location.line <= len(self.source_lines):
            line_num = err.location.line
            source_line = self.source_lines[line_num - 1]

            # Line number gutter
            gutter_width = len(str(line_num)) + 1
            lines.append(f"   \033[1;34m{'|':>{gutter_width}}\033[0m")
            lines.append(f" \033[1;34m{line_num} |\033[0m {source_line}")

            # Caret pointing to error
            caret_padding = ' ' * (err.location.column - 1)
            lines.append(f"   \033[1;34m{'|':>{gutter_width}}\033[0m {caret_padding}\033[1;31m^\033[0m")

        # Hint
        if err.hint:
            lines.append(f"   \033[1;32mhint\033[0m: {err.hint}")

        return '\n'.join(lines)

    def format_all(self) -> str:
        """Format all errors and warnings."""
        output = []

        for warn in self.warnings:
            output.append(self.format_error(warn))
            output.append("")

        for err in self.errors:
            output.append(self.format_error(err))
            output.append("")

        # Summary
        if self.errors or self.warnings:
            parts = []
            if self.errors:
                parts.append(f"{len(self.errors)} error(s)")
            if self.warnings:
                parts.append(f"{len(self.warnings)} warning(s)")
            output.append(f"\033[1m{' and '.join(parts)} generated\033[0m")

        return '\n'.join(output)

    def print_all(self):
        """Print all errors to stderr."""
        import sys
        if self.errors or self.warnings:
            print(self.format_all(), file=sys.stderr)
