"""
Saw Language Error Reporting
Provides nice error messages with source locations and context.
"""

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional, Dict


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
    CANNOT_COPY = auto()
    USE_AFTER_MOVE = auto()
    EXCLUSIVITY_VIOLATION = auto()

    # Warnings
    UNUSED_VARIABLE = auto()
    NON_EXHAUSTIVE_MATCH = auto()


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
        # Track sources from multiple files (for imports)
        self.sources: Dict[str, List[str]] = {filename: self.source_lines}

    def add_source(self, filename: str, source: str):
        """Add source from an imported module for error context."""
        self.sources[filename] = source.split('\n')

    # Design 144: a module-qualified type identity (`Header$m$dep`) and a
    # design-142 module-private symbol (`helper$m$dep`) are INTERNAL spellings.
    # `$` cannot occur in a Saw identifier, so nothing an author wrote can match
    # this, and rendering it for a human is always the short name. Scrubbing
    # here rather than at each message site makes the rule total: it holds for
    # every diagnostic in the compiler, including ones not yet written.
    _QUALIFIER_RE = re.compile(r"\$m\$[A-Za-z0-9_]+")

    @classmethod
    def humanize(cls, text: Optional[str]) -> Optional[str]:
        """Render internal module qualifiers out of a diagnostic string."""
        if not text:
            return text
        return cls._QUALIFIER_RE.sub("", text)

    def error(self, kind: ErrorKind, message: str, line: int, column: int,
              hint: Optional[str] = None, source_file: Optional[str] = None):
        """Report an error."""
        filename = source_file if source_file else self.filename
        loc = SourceLocation(line, column, filename)
        err = CompilerError(kind, self.humanize(message), loc,
                            self.humanize(hint), is_warning=False)
        self.errors.append(err)

    def warning(self, kind: ErrorKind, message: str, line: int, column: int,
                hint: Optional[str] = None, source_file: Optional[str] = None):
        """Report a warning."""
        filename = source_file if source_file else self.filename
        loc = SourceLocation(line, column, filename)
        warn = CompilerError(kind, self.humanize(message), loc,
                             self.humanize(hint), is_warning=True)
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

        # Get source lines for the correct file
        source_lines = self.sources.get(err.location.filename, self.source_lines)

        # Source context
        if 1 <= err.location.line <= len(source_lines):
            line_num = err.location.line
            source_line = source_lines[line_num - 1]

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
