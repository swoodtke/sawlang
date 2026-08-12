#!/usr/bin/env python3
"""A small LLM chat client for the LM Studio server on the LAN.

Speaks the OpenAI-compatible surface (/v1/models, /v1/chat/completions), which
is the portable one of the three LM Studio offers. Standard library only, so
there is nothing to install and every step maps cleanly onto the Saw port this
is the reference for.

This is the REFERENCE IMPLEMENTATION for design 215 — see
designs/215-llm-client-saw-port.md for the port plan and for the findings the
first Saw attempt (llm_client.saw, beside this file) produced.

    devtools/dogfood/programs/llm_client.py "say hello in five words"
    devtools/dogfood/programs/llm_client.py --list-models
    devtools/dogfood/programs/llm_client.py --stream "write a haiku about compilers"
    devtools/dogfood/programs/llm_client.py                       # interactive, vi keys, keeps history
    devtools/dogfood/programs/llm_client.py --tools "how many .saw files are in examples/?"
    devtools/dogfood/programs/llm_client.py --allow-writes "fix the typo on line 42 of notes.md"
    devtools/dogfood/programs/llm_client.py --system-prompt prompts/terse.txt
    devtools/dogfood/programs/llm_client.py --list-tools

Interactive sessions take SLASH COMMANDS -- /help lists them. They cover what
the API exposes per-session: /model and /models, /system (show, set, @file or
clear), /usage (cumulative and last-turn tokens, reasoning tokens included, plus
tok/s), /temp and /max-tokens, /tools and /stream toggles, /history, /clear,
/undo, /retry, and /save and /load for a conversation as JSON. A line beginning
`//` sends a literal leading slash.

TOOL USE is opt-in via --tools, and deliberately so: the file tools give the
model read access to everything under the tool root (the working directory by
default, LLM_TOOL_ROOT to move it), so turning them on should be a decision
rather than a default.

EDITING is gated twice. First behind --allow-writes (which implies --tools):
with it off, `replace_lines` is not merely refused but absent from the schemas
the model is shown. Second, and unconditionally, ON THE FILE BEING TRACKED BY
GIT — editing an untracked or ignored file is refused before it is even read,
and the check fails CLOSED, so "git is unavailable" also means "no edit". That
turns "it is all in git, so nothing can be lost" from an assumption into an
enforced invariant: every change this tool makes is undoable with
`git checkout -- <path>`.

Edits are otherwise confined to the tool root, written atomically (temp file
plus rename, preserving mode, so an interrupt loses the edit rather than the
file), and refuse a stale line range instead of clamping it. There is still no
shell and no exec tool.

Add tools by writing one @tool-decorated function.

Structured deliberately for porting: build request -> post -> parse -> print,
with the JSON and HTTP concerns kept apart.
"""

from __future__ import annotations

import argparse
import ast
import atexit
import difflib
import json
import operator
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

DEFAULT_HOST = "Mac-Studio.local"
DEFAULT_PORT = 1234
DEFAULT_TIMEOUT = 300.0  # generation is slow; this is a whole-response budget

# Tool sandboxing. Nothing here is a security boundary against a hostile local
# process; it is a guard against a confused model wandering out of the tree.
TOOL_ROOT = Path(os.environ.get("LLM_TOOL_ROOT") or Path.cwd())
READ_FILE_MAX_BYTES = 64 * 1024
LIST_FILES_MAX = 200
POW_EXPONENT_LIMIT = 64  # keeps `2 ** 10**9` from becoming a denial of service
DEFAULT_MAX_TOOL_ROUNDS = 6
WRITE_MAX_BYTES = 256 * 1024
DIFF_MAX_LINES = 60

# Mutating tools are gated separately from read-only ones: --tools alone stays
# read-only, and --allow-writes opens the edit tool. Flipped by main().
ALLOW_WRITES = False

HISTORY_FILE = Path(os.environ.get("LLM_CLIENT_HISTORY") or Path.home() / ".llm_client_history")
HISTORY_LENGTH = 1000

try:
    import readline
except ImportError:  # pragma: no cover - readline is absent on some builds
    readline = None  # type: ignore[assignment]


class LlmError(Exception):
    """A failure to report plainly, without a traceback."""


def _save_history() -> None:
    if readline is None:
        return
    try:
        readline.write_history_file(HISTORY_FILE)
    except OSError as exc:
        # Non-fatal, but say why: a history file that silently never appears is
        # worse than one line explaining what stopped it. Set LLM_CLIENT_HISTORY
        # to move it somewhere writable.
        print(f"llm_client: could not save history to {HISTORY_FILE}: {exc}", file=sys.stderr)


def setup_line_editing(mode: str = "vi") -> None:
    """Turn on readline editing with vi (or emacs) key bindings, plus history.

    macOS ships Python linked against libedit rather than GNU readline, and the
    two take different syntax for the mode switch. The catch that matters:
    libedit ACCEPTS the GNU spelling without raising and then ignores it, so
    trying one and catching the failure silently leaves you in emacs mode. This
    branches on the backend instead.
    """
    if readline is None or not sys.stdin.isatty():
        return

    doc = readline.__doc__ or ""
    libedit = getattr(readline, "backend", "") == "editline" or "libedit" in doc

    if mode == "vi":
        readline.parse_and_bind("bind -v" if libedit else "set editing-mode vi")
    else:
        readline.parse_and_bind("bind -e" if libedit else "set editing-mode emacs")

    try:
        readline.read_history_file(HISTORY_FILE)
    except FileNotFoundError:
        pass  # first run
    except OSError as exc:
        print(f"llm_client: could not read history from {HISTORY_FILE}: {exc}", file=sys.stderr)
    readline.set_history_length(HISTORY_LENGTH)
    atexit.register(_save_history)


# =============================================================================
# Tools
# =============================================================================


class ToolError(Exception):
    """A tool refused or failed.

    Reported back to the MODEL as the tool result rather than raised at the
    user: a model that passed a bad path can correct itself on the next round,
    and a crashed client cannot.
    """


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[..., str]
    mutating: bool = False


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, parameters: dict, mutating: bool = False):
    """Register a tool. The whole extension point: write one function.

    `mutating` gates the tool behind --allow-writes, and keeps it out of the
    schema list entirely when writes are off — a model that is never told about
    an edit tool cannot spend a round discovering it is forbidden.
    """

    def register(fn: Callable[..., str]) -> Callable[..., str]:
        TOOLS[name] = Tool(name, description, parameters, fn, mutating)
        return fn

    return register


def _within_root(target: Path, root: Path) -> bool:
    return target == root or root in target.parents


def _resolve_in_root(path_str: str) -> Path:
    """Resolve `path_str` under TOOL_ROOT, refusing anything that escapes it.

    Resolution happens BEFORE the check so that `..` segments and symlinks are
    already collapsed — checking the unresolved path would be trivially fooled.
    """
    root = TOOL_ROOT.resolve()
    target = Path(path_str).resolve() if os.path.isabs(path_str) else (root / path_str).resolve()
    if not _within_root(target, root):
        raise ToolError(f"path is outside the tool root ({root}): {path_str}")
    return target


@tool(
    "get_time",
    "The current local date and time. Takes no arguments.",
    {"type": "object", "properties": {}},
)
def _get_time() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


_ARITH_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_arith(node: ast.AST) -> float | int:
    """Evaluate an arithmetic AST. Deliberately not eval(): this accepts numbers
    and operators and nothing else, so no name, call or attribute can appear."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ToolError(f"only numbers are allowed, got {node.value!r}")
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ARITH_OPS:
        return _ARITH_OPS[type(node.op)](_eval_arith(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITH_OPS:
        left = _eval_arith(node.left)
        right = _eval_arith(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > POW_EXPONENT_LIMIT:
            raise ToolError(f"exponent {right} exceeds the limit of {POW_EXPONENT_LIMIT}")
        try:
            return _ARITH_OPS[type(node.op)](left, right)
        except ZeroDivisionError:
            raise ToolError("division by zero") from None
    raise ToolError(f"unsupported syntax in expression: {type(node).__name__}")


@tool(
    "calculate",
    "Evaluate an arithmetic expression over numbers. Supports + - * / // % ** "
    "parentheses and unary minus. No variables or function calls.",
    {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "for example (17 * 23) + 4"}
        },
        "required": ["expression"],
    },
)
def _calculate(expression: str) -> str:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"not a valid expression: {exc.msg}") from exc
    return str(_eval_arith(tree.body))


@tool(
    "list_files",
    "List files under the tool root matching a glob pattern. Use this to find "
    "files before reading them.",
    {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "glob relative to the tool root, e.g. '*.md' or 'examples/*.saw'",
            }
        },
        "required": ["pattern"],
    },
)
def _list_files(pattern: str) -> str:
    if ".." in Path(pattern).parts:
        raise ToolError("'..' is not allowed in a pattern")
    if os.path.isabs(pattern):
        raise ToolError("the pattern must be relative to the tool root")
    root = TOOL_ROOT.resolve()
    try:
        found = sorted(p for p in root.glob(pattern) if p.is_file())
    except (OSError, ValueError) as exc:
        raise ToolError(f"bad pattern {pattern!r}: {exc}") from exc
    # Re-check each hit: a symlink inside the tree can still point outside it.
    inside = [p for p in found if _within_root(p.resolve(), root)]
    if not inside:
        return f"no files match {pattern!r}"
    shown = inside[:LIST_FILES_MAX]
    lines = [str(p.relative_to(root)) for p in shown]
    if len(inside) > len(shown):
        lines.append(f"... and {len(inside) - len(shown)} more ({len(inside)} total)")
    else:
        lines.append(f"({len(inside)} file{'s' if len(inside) != 1 else ''})")
    return "\n".join(lines)


@tool(
    "read_file",
    "Read a UTF-8 text file under the tool root.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "path relative to the tool root"}
        },
        "required": ["path"],
    },
)
def _read_file(path: str) -> str:
    target = _resolve_in_root(path)
    if not target.exists():
        raise ToolError(f"no such file: {path}")
    if not target.is_file():
        raise ToolError(f"not a regular file: {path}")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise ToolError(f"could not read {path}: {exc}") from exc
    text = raw[:READ_FILE_MAX_BYTES].decode("utf-8", "replace")
    if len(raw) > READ_FILE_MAX_BYTES:
        text += f"\n... [truncated: {len(raw)} bytes total, showing {READ_FILE_MAX_BYTES}]"
    return text


def _git_state(target: Path) -> tuple[bool, str]:
    """Returns (editable, description).

    `editable` is the gate on every write: a file git does not TRACK has no
    recoverable previous version, so an edit to it is irreversible and is
    refused outright. A tracked file with uncommitted changes is still
    editable — the last commit is recoverable — but the description says so,
    because uncommitted work is not.

    Fails CLOSED. If git cannot be run, or the answer cannot be determined,
    the verdict is "not editable": the whole point is that recoverability is
    established rather than assumed.
    """
    root = str(TOOL_ROOT.resolve())

    def git(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *argv], cwd=root, capture_output=True, text=True, timeout=5
        )

    try:
        if git("rev-parse", "--is-inside-work-tree").returncode != 0:
            return False, f"the tool root ({root}) is not a git repository"
        # Tracking is asked about directly rather than inferred from `status`,
        # which prints NOTHING for an ignored file and would read as "clean".
        if git("ls-files", "--error-unmatch", "--", str(target)).returncode != 0:
            return False, "the file is not tracked by git (untracked or ignored)"
        if git("status", "--porcelain", "--", str(target)).stdout.strip():
            return True, "tracked, with uncommitted changes already present before this edit"
        return True, "tracked and clean before this edit - `git checkout --` undoes this"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"the git state could not be determined ({type(exc).__name__})"


def _atomic_write(target: Path, text: str) -> None:
    """Replace `target`'s contents without ever leaving it half-written.

    Writes a sibling temp file and renames over the original: os.replace is
    atomic within a filesystem, so an interrupt loses the edit rather than the
    file. The original mode is copied across first, which matters because a
    fresh temp file is 0600 and would silently de-executable a script.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".llm_client.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@tool(
    "replace_lines",
    "Replace an inclusive 1-based line range of a text file with new content. "
    "ONLY works on files tracked by git; editing an untracked or ignored file "
    "is refused, because the change would not be recoverable. "
    "Use read_file first to see current line numbers. "
    "To DELETE lines, pass an empty content string. "
    "To INSERT before line N without deleting anything, pass start_line=N and "
    "end_line=N-1. Returns a unified diff of what changed.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "path relative to the tool root"},
            "start_line": {"type": "integer", "description": "first line to replace, 1-based"},
            "end_line": {
                "type": "integer",
                "description": "last line to replace, inclusive; start_line-1 to insert",
            },
            "content": {
                "type": "string",
                "description": "replacement text; empty string deletes the range",
            },
        },
        "required": ["path", "start_line", "end_line", "content"],
    },
    mutating=True,
)
def _replace_lines(path: str, start_line: int, end_line: int, content: str) -> str:
    if not ALLOW_WRITES:
        raise ToolError("writing is disabled; restart the client with --allow-writes")
    if len(content.encode("utf-8")) > WRITE_MAX_BYTES:
        raise ToolError(f"content exceeds the {WRITE_MAX_BYTES} byte limit")

    target = _resolve_in_root(path)
    if not target.exists():
        raise ToolError(f"no such file: {path} (this tool edits existing files only)")
    if not target.is_file():
        raise ToolError(f"not a regular file: {path}")

    # THE GATE: no edit to anything git does not track. Checked before the file
    # is even read, so a refused edit touches nothing.
    editable, git_note = _git_state(target)
    if not editable:
        raise ToolError(
            f"refusing to edit {path}: {git_note}. Only git-tracked files can be "
            f"edited, so that every change this tool makes is recoverable with "
            f"`git checkout -- {path}`. Commit or `git add` the file first."
        )

    raw = target.read_bytes()
    try:
        original = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(f"{path} is not UTF-8 text; refusing to edit it") from exc

    lines = original.splitlines(keepends=True)
    total = len(lines)

    # Out of range is an ERROR, not a clamp: it means the model is working from
    # a stale view of the file, and silently editing the wrong place is the one
    # outcome worth refusing outright. Reporting the real length lets it re-read.
    if start_line < 1:
        raise ToolError(f"start_line must be >= 1, got {start_line}")
    if end_line < start_line - 1:
        raise ToolError(
            f"end_line ({end_line}) must be >= start_line - 1 ({start_line - 1}); "
            f"use end_line = start_line - 1 to insert without deleting"
        )
    if start_line > total + 1:
        raise ToolError(f"start_line {start_line} is past the end: {path} has {total} lines")
    if end_line > total:
        raise ToolError(f"end_line {end_line} is past the end: {path} has {total} lines")

    replacement = content.splitlines(keepends=True)
    # Keep the file's line structure intact: a replacement block that does not
    # end in a newline would otherwise weld itself onto the following line.
    if replacement and not replacement[-1].endswith(("\n", "\r")):
        following = end_line < total
        if following or original.endswith(("\n", "\r")):
            replacement[-1] += "\n"

    updated = lines[: start_line - 1] + replacement + lines[end_line:]
    new_text = "".join(updated)
    if new_text == original:
        return f"no change: the requested content already matches lines {start_line}-{end_line}"

    _atomic_write(target, new_text)

    diff = list(
        difflib.unified_diff(
            lines, updated, fromfile=f"{path} (before)", tofile=f"{path} (after)", n=2
        )
    )
    shown = [line.rstrip("\n") for line in diff[:DIFF_MAX_LINES]]
    if len(diff) > DIFF_MAX_LINES:
        shown.append(f"... [diff truncated, {len(diff)} lines total]")

    removed = end_line - start_line + 1
    return (
        f"replaced lines {start_line}-{end_line} of {path} "
        f"({removed} line{'s' if removed != 1 else ''} out, {len(replacement)} in; "
        f"{total} -> {len(updated)} lines). Before the edit it was {git_note}.\n"
        + "\n".join(shown)
    )


def tool_specs() -> list[dict]:
    """The tool list in the shape /v1/chat/completions expects.

    Mutating tools are omitted unless writes are enabled, so the model's view of
    what it can do matches what it is actually allowed to do.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOLS.values()
        if ALLOW_WRITES or not t.mutating
    ]


def dispatch_tool(name: str, arguments: str) -> str:
    """Run one tool call and return its result as the text the model will see.

    Every failure path returns a message rather than raising: the model is the
    audience, and "you passed a path outside the root" lets it try again.
    """
    entry = TOOLS.get(name)
    if entry is None:
        return f"error: no such tool {name!r}. Available: {', '.join(TOOLS)}"
    # Belt and braces: the schema list already hides mutating tools when writes
    # are off, but a model can name a tool it was never offered.
    if entry.mutating and not ALLOW_WRITES:
        return f"error: {name} needs --allow-writes, which is off"
    try:
        parsed = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError as exc:
        # Models really do emit malformed argument JSON; this is a normal path.
        return f"error: arguments were not valid JSON ({exc}). Received: {arguments[:200]}"
    if not isinstance(parsed, dict):
        return f"error: arguments must be a JSON object, got {type(parsed).__name__}"
    try:
        return entry.run(**parsed)
    except ToolError as exc:
        return f"error: {exc}"
    except TypeError as exc:
        return f"error: wrong arguments for {name}: {exc}"
    except Exception as exc:  # noqa: BLE001 - a tool bug must not kill the session
        return f"error: {name} raised {type(exc).__name__}: {exc}"


@dataclass
class Completion:
    """One assistant reply plus whatever the server said it cost."""

    message: dict
    usage: dict | None = None


class Client:
    def __init__(self, host: str, port: int, timeout: float = DEFAULT_TIMEOUT):
        self.base = f"http://{host}:{port}"
        self.timeout = timeout

    def _open(self, path: str, payload: dict | None = None):
        url = self.base + path
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace").strip()
            raise LlmError(f"{url} -> HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise LlmError(f"cannot reach {url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LlmError(f"{url} timed out after {self.timeout:g}s") from exc

    def models(self) -> list[str]:
        with self._open("/v1/models") as resp:
            doc = json.load(resp)
        return [entry["id"] for entry in doc.get("data", []) if "id" in entry]

    def pick_model(self) -> str:
        """The first model that looks like a chat model, for running with no flags."""
        ids = self.models()
        chat = [m for m in ids if "embed" not in m.lower()]
        if not chat:
            raise LlmError(f"no chat model on the server (saw: {', '.join(ids) or 'nothing'})")
        return chat[0]

    def _sampling(self, payload: dict, temperature: float | None, max_tokens: int | None) -> None:
        """Attach the sampling knobs only when set, so the server's own defaults
        apply when the user has not chosen."""
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

    def complete(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        """One non-streaming round, returning the assistant message VERBATIM.

        Verbatim is the point: the message carries the tool_call ids that the
        follow-up tool results have to quote back exactly, so it goes into the
        history as the server sent it rather than rebuilt from parts.
        """
        payload: dict = {"model": model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        self._sampling(payload, temperature, max_tokens)
        with self._open("/v1/chat/completions", payload) as resp:
            doc = json.load(resp)
        choices = doc.get("choices") or []
        if not choices:
            raise LlmError(f"no choices in the response: {json.dumps(doc)[:400]}")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise LlmError(f"no assistant message in the response: {json.dumps(doc)[:400]}")
        return Completion(message=message, usage=doc.get("usage"))

    def chat(self, model: str, messages: list[dict]) -> str:
        content = self.complete(model, messages).message.get("content")
        if content is None:
            raise LlmError("the response carried no message content")
        return content

    def chat_stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
        usage_sink: dict | None = None,
    ) -> Iterator[str]:
        """Yields content deltas as they arrive (server-sent events).

        `stream_options.include_usage` asks for a final usage-only frame, which
        LM Studio sends with an empty `choices` list; it is copied into
        `usage_sink` so a streamed turn still counts toward /usage.
        """
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        self._sampling(payload, temperature, max_tokens)
        with self._open("/v1/chat/completions", payload) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue  # a keep-alive or a partial frame
                if usage_sink is not None and isinstance(event.get("usage"), dict):
                    usage_sink.update(event["usage"])
                for choice in event.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield piece


def _compact(text: str, limit: int = 90) -> str:
    """One-line, length-capped rendering for the [tool] trace."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


@dataclass
class Session:
    """Everything one conversation carries, so the turn loop and the slash
    commands share one mutable place rather than a widening argument list.

    The system prompt is held APART from `history` instead of living at
    index 0: /clear then empties the conversation without disturbing it, and
    /system replaces it without any index juggling.
    """

    client: Client
    model: str
    system: str | None = None
    history: list[dict] = field(default_factory=list)
    stream: bool = False
    use_tools: bool = False
    max_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    temperature: float | None = None
    max_tokens: int | None = None

    # Running totals for /usage.
    turns: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    unreported_turns: int = 0
    last_usage: dict | None = None
    last_seconds: float = 0.0

    def messages(self) -> list[dict]:
        head = [{"role": "system", "content": self.system}] if self.system else []
        return head + self.history

    def record(self, usage: dict | None, seconds: float) -> None:
        self.turns += 1
        self.last_seconds = seconds
        if not usage:
            self.unreported_turns += 1
            self.last_usage = None
            return
        self.last_usage = usage
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        details = usage.get("completion_tokens_details") or {}
        self.reasoning_tokens += int(details.get("reasoning_tokens") or 0)


def _drive(session: Session, trace: bool = True) -> str:
    """Run the current history to a final text answer, executing tool calls."""
    specs = tool_specs() if session.use_tools else None
    started = time.monotonic()

    # Streaming and tool use do not compose here: a tool round has to see the
    # whole message before it can dispatch. Tools win when both are asked for,
    # and main() says so once rather than silently dropping one.
    if specs is None and session.stream:
        sink: dict = {}
        parts: list[str] = []
        for piece in session.client.chat_stream(
            session.model,
            session.messages(),
            session.temperature,
            session.max_tokens,
            usage_sink=sink,
        ):
            sys.stdout.write(piece)
            sys.stdout.flush()
            parts.append(piece)
        sys.stdout.write("\n")
        reply = "".join(parts)
        session.history.append({"role": "assistant", "content": reply})
        session.record(sink or None, time.monotonic() - started)
        return reply

    usage: dict | None = None
    for _round in range(session.max_rounds):
        result = session.client.complete(
            session.model,
            session.messages(),
            specs,
            session.temperature,
            session.max_tokens,
        )
        message = result.message
        # Usage is per REQUEST, so a tool turn spans several; keep the last,
        # which is the one whose prompt included every tool result.
        usage = result.usage or usage
        session.history.append(message)

        calls = message.get("tool_calls") or []
        if not calls:
            reply = message.get("content") or ""
            print(reply)
            session.record(usage, time.monotonic() - started)
            return reply

        # A model may interleave commentary with its tool calls; show it.
        said = (message.get("content") or "").strip()
        if said and trace:
            print(said)

        for call in calls:
            function = call.get("function") or {}
            name = function.get("name") or "<unnamed>"
            raw_args = function.get("arguments") or "{}"
            tool_result = dispatch_tool(name, raw_args)
            if trace:
                print(
                    f"[tool] {name}({_compact(raw_args, 60)}) -> {_compact(tool_result, 120)}",
                    file=sys.stderr,
                )
            session.history.append(
                {"role": "tool", "tool_call_id": call.get("id"), "content": tool_result}
            )

    plural = "" if session.max_rounds == 1 else "s"
    raise LlmError(
        f"the model was still calling tools after {session.max_rounds} round{plural}; "
        f"raise --max-tool-rounds if that is expected"
    )


def run_turn(session: Session, prompt: str) -> str:
    """Add one user message and drive it to an answer.

    Rolls the whole turn back on failure: a `tool_calls` message left in
    history with no matching result makes every later request invalid, so a
    half-recorded turn is worse than a dropped one.
    """
    mark = len(session.history)
    session.history.append({"role": "user", "content": prompt})
    try:
        return _drive(session)
    except LlmError:
        del session.history[mark:]
        raise


def run_once(session: Session, prompt: str) -> None:
    run_turn(session, prompt)


# =============================================================================
# Interactive slash commands
# =============================================================================
#
# Same shape as the tool registry: a name-keyed table of small handlers. Each
# returns True to keep the session going, False to quit.


@dataclass(frozen=True)
class Command:
    name: str
    usage: str
    help: str
    run: Callable[[Session, str], bool]


COMMANDS: dict[str, Command] = {}
ALIASES: dict[str, str] = {}


def command(name: str, usage: str, help: str, aliases: tuple[str, ...] = ()):
    def register(fn: Callable[[Session, str], bool]) -> Callable[[Session, str], bool]:
        COMMANDS[name] = Command(name, usage, help, fn)
        for alias in aliases:
            ALIASES[alias] = name
        return fn

    return register


def _onoff(arg: str, current: bool) -> bool:
    """Parse an on/off argument, treating a bare command as a toggle."""
    token = arg.strip().lower()
    if token in ("on", "yes", "true", "1"):
        return True
    if token in ("off", "no", "false", "0"):
        return False
    if not token:
        return not current
    raise ValueError(f"expected on or off, got {arg!r}")


@command("/help", "/help", "list these commands", aliases=("/?",))
def _cmd_help(session: Session, arg: str) -> bool:
    width = max(len(c.usage) for c in COMMANDS.values())
    for entry in COMMANDS.values():
        print(f"  {entry.usage:<{width}}  {entry.help}")
    print("\n  A line starting with // sends a literal leading slash.")
    return True


@command("/quit", "/quit", "leave (blank line and Ctrl-D also work)", aliases=("/exit", "/q"))
def _cmd_quit(session: Session, arg: str) -> bool:
    return False


@command("/model", "/model [id]", "show the current model, or switch to another")
def _cmd_model(session: Session, arg: str) -> bool:
    wanted = arg.strip()
    if not wanted:
        print(f"model: {session.model}")
        return True
    available = session.client.models()
    if wanted not in available:
        # Refuse rather than let the next turn fail with a server 400.
        print(f"no such model: {wanted}", file=sys.stderr)
        print(f"available: {', '.join(available)}", file=sys.stderr)
        return True
    session.model = wanted
    print(f"model: {session.model}")
    return True


@command("/models", "/models", "list the models the server has loaded")
def _cmd_models(session: Session, arg: str) -> bool:
    for name in session.client.models():
        print(f"  {'* ' if name == session.model else '  '}{name}")
    return True


@command(
    "/system",
    "/system [text|@file|clear]",
    "show, set, load from a file, or drop the system prompt",
)
def _cmd_system(session: Session, arg: str) -> bool:
    text = arg.strip()
    if not text:
        print(session.system if session.system else "(no system prompt)")
        return True
    if text == "clear":
        session.system = None
        print("system prompt cleared")
        return True
    if text.startswith("@"):
        try:
            session.system = Path(text[1:]).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            print(f"could not read {text[1:]}: {exc}", file=sys.stderr)
            return True
        print(f"system prompt loaded from {text[1:]} ({len(session.system)} chars)")
        return True
    session.system = text
    print(f"system prompt set ({len(text)} chars)")
    return True


@command("/usage", "/usage", "token usage for this session", aliases=("/stats",))
def _cmd_usage(session: Session, arg: str) -> bool:
    total = session.prompt_tokens + session.completion_tokens
    print(f"  turns            {session.turns}")
    print(f"  prompt tokens    {session.prompt_tokens}")
    print(f"  completion       {session.completion_tokens}")
    if session.reasoning_tokens:
        print(f"    of which reasoning {session.reasoning_tokens}")
    print(f"  total            {total}")
    if session.last_usage:
        last = session.last_usage
        done = int(last.get("completion_tokens") or 0)
        rate = f", {done / session.last_seconds:.1f} tok/s" if session.last_seconds else ""
        print(f"  last turn        {last.get('total_tokens')} tokens in "
              f"{session.last_seconds:.1f}s{rate}")
    if session.unreported_turns:
        print(f"  ({session.unreported_turns} turn(s) reported no usage)")
    return True


@command("/history", "/history", "show the conversation as the server will see it")
def _cmd_history(session: Session, arg: str) -> bool:
    messages = session.messages()
    if not messages:
        print("(empty)")
        return True
    for index, message in enumerate(messages):
        role = message.get("role", "?")
        if message.get("tool_calls"):
            names = ", ".join(
                (c.get("function") or {}).get("name", "?") for c in message["tool_calls"]
            )
            body = f"<tool_calls: {names}>"
        else:
            body = _compact(str(message.get("content") or ""), 96)
        print(f"  [{index}] {role:9} {body}")
    return True


@command("/clear", "/clear", "forget the conversation, keeping the system prompt", aliases=("/reset",))
def _cmd_clear(session: Session, arg: str) -> bool:
    session.history.clear()
    print("conversation cleared")
    return True


@command("/undo", "/undo", "drop the last exchange")
def _cmd_undo(session: Session, arg: str) -> bool:
    for index in range(len(session.history) - 1, -1, -1):
        if session.history[index].get("role") == "user":
            del session.history[index:]
            print("dropped the last exchange")
            return True
    print("nothing to undo")
    return True


@command("/retry", "/retry", "run the last prompt again", aliases=("/regen",))
def _cmd_retry(session: Session, arg: str) -> bool:
    for index in range(len(session.history) - 1, -1, -1):
        if session.history[index].get("role") == "user":
            prompt = str(session.history[index].get("content") or "")
            del session.history[index:]
            try:
                run_turn(session, prompt)
            except LlmError as exc:
                print(f"error: {exc}", file=sys.stderr)
            return True
    print("nothing to retry")
    return True


@command("/tools", "/tools [on|off]", "toggle tool use, or list the tools in force")
def _cmd_tools(session: Session, arg: str) -> bool:
    try:
        session.use_tools = _onoff(arg, session.use_tools)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return True
    if session.use_tools:
        offered = [s["function"]["name"] for s in tool_specs()]
        print(f"tools on: {', '.join(offered)}")
        if not ALLOW_WRITES:
            print("  (read-only; restart with --allow-writes to enable editing)")
    else:
        print("tools off")
    return True


@command("/stream", "/stream [on|off]", "toggle token streaming (ignored while tools are on)")
def _cmd_stream(session: Session, arg: str) -> bool:
    try:
        session.stream = _onoff(arg, session.stream)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return True
    note = " (tools are on, so this has no effect until /tools off)" if session.use_tools else ""
    print(f"stream {'on' if session.stream else 'off'}{note}")
    return True


@command("/temp", "/temp [value]", "show or set sampling temperature", aliases=("/temperature",))
def _cmd_temp(session: Session, arg: str) -> bool:
    text = arg.strip()
    if not text:
        print(f"temperature: {session.temperature if session.temperature is not None else 'server default'}")
        return True
    if text in ("default", "reset"):
        session.temperature = None
        print("temperature: server default")
        return True
    try:
        session.temperature = float(text)
    except ValueError:
        print(f"not a number: {text}", file=sys.stderr)
        return True
    print(f"temperature: {session.temperature}")
    return True


@command("/max-tokens", "/max-tokens [n]", "cap the reply length (default: server's own)")
def _cmd_max_tokens(session: Session, arg: str) -> bool:
    text = arg.strip()
    if not text:
        print(f"max_tokens: {session.max_tokens if session.max_tokens is not None else 'server default'}")
        return True
    if text in ("default", "reset"):
        session.max_tokens = None
        print("max_tokens: server default")
        return True
    try:
        session.max_tokens = int(text)
    except ValueError:
        print(f"not an integer: {text}", file=sys.stderr)
        return True
    print(f"max_tokens: {session.max_tokens}")
    return True


@command("/save", "/save <file>", "write the conversation to a JSON file")
def _cmd_save(session: Session, arg: str) -> bool:
    target = arg.strip()
    if not target:
        print("usage: /save <file>", file=sys.stderr)
        return True
    doc = {"model": session.model, "system": session.system, "history": session.history}
    try:
        Path(target).expanduser().write_text(json.dumps(doc, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"could not write {target}: {exc}", file=sys.stderr)
        return True
    print(f"saved {len(session.history)} messages to {target}")
    return True


@command("/load", "/load <file>", "replace the conversation from a JSON file")
def _cmd_load(session: Session, arg: str) -> bool:
    target = arg.strip()
    if not target:
        print("usage: /load <file>", file=sys.stderr)
        return True
    try:
        doc = json.loads(Path(target).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not load {target}: {exc}", file=sys.stderr)
        return True
    if not isinstance(doc, dict) or not isinstance(doc.get("history"), list):
        print(f"{target} is not a conversation file", file=sys.stderr)
        return True
    session.history = doc["history"]
    session.system = doc.get("system") or session.system
    if doc.get("model"):
        session.model = doc["model"]
    print(f"loaded {len(session.history)} messages from {target}")
    return True


def handle_command(session: Session, line: str) -> bool:
    """Dispatch a /command. Returns False only when the session should end."""
    head, _, arg = line.partition(" ")
    name = ALIASES.get(head, head)
    entry = COMMANDS.get(name)
    if entry is None:
        print(f"unknown command {head} - try /help", file=sys.stderr)
        return True
    try:
        return entry.run(session, arg)
    except LlmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return True


def run_interactive(session: Session, edit_mode: str = "vi") -> None:
    setup_line_editing(edit_mode)
    keys = f"{edit_mode} keys" if readline is not None and sys.stdin.isatty() else "no line editing"
    if session.use_tools:
        tools_note = f"; {len(tool_specs())} tools" + (
            ", WRITES ENABLED" if ALLOW_WRITES else ", read-only"
        )
    else:
        tools_note = ""
    print(f"model: {session.model}   ({keys}{tools_note}; /help for commands, /quit to leave)")
    if session.system:
        print(f"system prompt: {_compact(session.system, 70)}")

    while True:
        # The newline is printed rather than folded into the prompt: readline
        # tracks the cursor column from the prompt string, and an embedded
        # newline throws off redraw when you edit a recalled line.
        print()
        try:
            line = input("> ").strip()
        except EOFError:
            print()
            return
        if not line:
            return
        if line.startswith("//"):
            line = line[1:]  # escape hatch for a prompt that really starts with /
        elif line.startswith("/"):
            if not handle_command(session, line):
                return
            continue
        try:
            run_turn(session, line)
        except LlmError as exc:
            print(f"error: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("prompt", nargs="*", help="the prompt; omit for interactive mode")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", help="default: the server's first non-embedding model")
    parser.add_argument("--stream", action="store_true", help="print tokens as they arrive")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument(
        "--edit-mode",
        choices=("vi", "emacs"),
        default="vi",
        help="interactive key bindings (default: vi)",
    )
    parser.add_argument(
        "--tools",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=f"let the model call tools (read-only, confined to {TOOL_ROOT}); off by default",
    )
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="also expose the file-EDITING tool (implies --tools). Edits are atomic, "
        "confined to the tool root, and REFUSED on any file git does not track.",
    )
    parser.add_argument("--list-tools", action="store_true", help="print the tool schemas and exit")
    parser.add_argument(
        "--max-tool-rounds",
        type=int,
        default=DEFAULT_MAX_TOOL_ROUNDS,
        help=f"cap on tool round-trips per turn (default: {DEFAULT_MAX_TOOL_ROUNDS})",
    )
    parser.add_argument(
        "--system-prompt",
        metavar="FILE",
        help="file whose contents become the system prompt",
    )
    parser.add_argument("--temperature", type=float, help="sampling temperature")
    parser.add_argument("--max-tokens", type=int, help="cap the reply length")
    args = parser.parse_args()

    global ALLOW_WRITES
    ALLOW_WRITES = args.allow_writes
    if args.allow_writes:
        args.tools = True

    if args.list_tools:
        print(f"tool root: {TOOL_ROOT.resolve()}")
        gated = [t.name for t in TOOLS.values() if t.mutating and not ALLOW_WRITES]
        if gated:
            print(f"hidden without --allow-writes: {', '.join(gated)}")
        print(json.dumps(tool_specs(), indent=2))
        return 0

    if args.stream and args.tools:
        print(
            "llm_client: --stream is ignored while --tools is on (a tool round needs "
            "the whole message before it can dispatch); use --no-tools to stream.",
            file=sys.stderr,
        )

    system: str | None = None
    if args.system_prompt:
        try:
            system = Path(args.system_prompt).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            print(f"llm_client: could not read {args.system_prompt}: {exc}", file=sys.stderr)
            return 1

    client = Client(args.host, args.port, args.timeout)
    try:
        if args.list_models:
            for name in client.models():
                print(name)
            return 0

        session = Session(
            client=client,
            model=args.model or client.pick_model(),
            system=system,
            stream=args.stream,
            use_tools=args.tools,
            max_rounds=args.max_tool_rounds,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        prompt = " ".join(args.prompt).strip()
        if prompt:
            run_once(session, prompt)
        else:
            run_interactive(session, args.edit_mode)
    except LlmError as exc:
        print(f"llm_client: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
