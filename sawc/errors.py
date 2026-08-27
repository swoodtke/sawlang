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
    # Design 150: two imports in one file claiming the same module qualifier.
    DUPLICATE_IMPORT = auto()
    # DF-232e: modules that import each other, directly or around a longer
    # loop. There is no order in which to check them, so the compiler names the
    # loop instead of picking one arbitrarily and letting the failure land on
    # whichever module happened to lose.
    IMPORT_CYCLE = auto()
    # Design 198: two arms of one `match` with the same pattern.
    DUPLICATE_MATCH_ARM = auto()
    WRONG_ARGUMENT_COUNT = auto()
    IMMUTABLE_ASSIGNMENT = auto()
    INVALID_BREAK_CONTINUE = auto()
    CANNOT_COPY = auto()
    # Design 246: a type whose storage transitively contains its own storage
    # INLINE. The layout has no finite size, so the declaration is refused
    # rather than reaching codegen, where it used to be an internal compiler
    # error about an undefined type (DF-260a).
    RECURSIVE_TYPE = auto()
    USE_AFTER_MOVE = auto()
    EXCLUSIVITY_VIOLATION = auto()

    # Warnings
    UNUSED_VARIABLE = auto()
    NON_EXHAUSTIVE_MATCH = auto()


# Design 150 section 4b: the `-W` surface. Warnings are OFF by default, never
# affect the exit code, and there is no `-Werror` yet. `-W <name>` (repeatable)
# and `-W all` turn categories on. This is policy for ONE invocation of the
# compiler rather than state of one reporter — the pipeline builds several
# reporters per compile (the builtin check, the entry check, the coroutine
# transform's re-check) and a warning means the same thing in all of them.
WARNING_CATEGORIES: Dict[str, str] = {
    "shadowed-qualifier":
        "a declaration takes the name of a module qualifier bound by an "
        "import, so qualified access is unavailable in its scope",
}

_enabled_warnings: set = set()

# Locations already warned about. Invocation-wide, not per-reporter: the
# pipeline re-enters its front half (place lowering, then the coroutine
# transform) with a FRESH reporter each time, and one declaration deserves one
# warning however many times the compiler walks past it.
_warned_locations: set = set()


def enable_warnings(names) -> List[str]:
    """Turn on the named warning categories; `all` turns on every one.

    Returns the names that matched no category, for the caller to report."""
    unknown = []
    for name in names:
        if name == "all":
            _enabled_warnings.update(WARNING_CATEGORIES)
        elif name in WARNING_CATEGORIES:
            _enabled_warnings.add(name)
        else:
            unknown.append(name)
    return unknown


def warning_enabled(category: Optional[str]) -> bool:
    """Whether a warning of this category should be reported. An uncategorized
    warning is always reported — only the `-W` categories are opt-in."""
    if category is None:
        return True
    return category in _enabled_warnings


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
    # The `-W` category this warning belongs to, printed alongside it so the
    # reader knows which flag turned it on and which would turn it off.
    category: Optional[str] = None


class ErrorReporter:
    """Collects and formats compiler errors."""

    def __init__(self, source: str, filename: str = "<input>"):
        self.source = source
        self.source_lines = source.split('\n')
        self.filename = filename
        self.errors: List[CompilerError] = []
        self.warnings: List[CompilerError] = []
        # Every error already reported, keyed by everything a reader can see.
        # See `error()`.
        self._reported: set = set()
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
        """Report an error, unless this exact one was already reported.

        Two diagnostics identical in kind, message, hint AND position are one
        diagnostic to a reader — printing the second only makes the first look
        like it happened twice. The warning path has deduplicated on the same
        grounds since design 150, for the same underlying reason: a declaration
        is checked again by every pass that re-enters the front half.

        Design 179 (`#lend_var`) made that reason structural rather than
        incidental. A flavored accessor is compiled as TWO methods over ONE
        piece of source, so a mistake in the part both specializations share was
        reported once per specialization, at the same line, with the same text
        (DF-179a). Deduplicating here keeps that an implementation detail
        instead of something an author has to know about.
        """
        filename = source_file if source_file else self.filename
        loc = SourceLocation(line, column, filename)
        err = CompilerError(kind, self.humanize(message), loc,
                            self.humanize(hint), is_warning=False)
        key = (kind, err.message, err.hint, filename, line, column)
        if key in self._reported:
            return
        self._reported.add(key)
        self.errors.append(err)

    def warning(self, kind: ErrorKind, message: str, line: int, column: int,
                hint: Optional[str] = None, source_file: Optional[str] = None,
                category: Optional[str] = None):
        """Report a warning.

        A `category` names a `-W` opt-in (design 150): the warning is dropped
        unless that category was enabled, and a duplicate at one location is
        reported once — the same declaration is checked again by every pass
        that re-enters the front half."""
        if not warning_enabled(category):
            return
        filename = source_file if source_file else self.filename
        loc = SourceLocation(line, column, filename)
        warn = CompilerError(kind, self.humanize(message), loc,
                             self.humanize(hint), is_warning=True,
                             category=category)
        key = (category, warn.message, filename, line, column)
        if key in _warned_locations:
            return
        _warned_locations.add(key)
        self.warnings.append(warn)

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def format_error(self, err: CompilerError) -> str:
        """Format a single error with source context."""
        lines = []

        # Error header. A warning is yellow and names its `-W` category, so the
        # reader can see at a glance which flag produced it (design 150).
        if err.is_warning:
            label = "warning"
            if err.category:
                label = f"warning [-W {err.category}]"
            lines.append(f"\033[1;33m{label}\033[0m: {err.message}")
        else:
            lines.append(f"\033[1;31merror\033[0m: {err.message}")

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

            # Caret pointing to the error (yellow on a warning, matching header)
            caret_padding = ' ' * (err.location.column - 1)
            caret_color = "1;33" if err.is_warning else "1;31"
            lines.append(f"   \033[1;34m{'|':>{gutter_width}}\033[0m {caret_padding}\033[{caret_color}m^\033[0m")

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

    def print_warnings(self):
        """Print collected warnings to stderr and forget them.

        A clean compile still has to say its warnings out loud (design 150):
        `print_all` runs only on the failure path, so without this a `-W`
        category would be collected and silently dropped. Forgetting them keeps
        a later `print_all` from repeating what was already shown."""
        import sys
        if not self.warnings:
            return
        out = []
        for warn in self.warnings:
            out.append(self.format_error(warn))
            out.append("")
        out.append(f"\033[1m{len(self.warnings)} warning(s) generated\033[0m")
        print('\n'.join(out), file=sys.stderr)
        self.warnings = []
