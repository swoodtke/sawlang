# Design 215 — the LLM client: a working Python reference, and the Saw port it exists for

**Status: the Python REFERENCE is LANDED and working. STAGES A-C of the Saw
port LANDED Aug 26** (dogfood-agent rewrite — see "The stage A-C rewrite"
section at the end for its findings, DF-215f through DF-215j). Stages D-F
remain future work. Both programs live in `devtools/dogfood/programs/`:

- `llm_client.py` — the reference. Verified against LM Studio on
  `Mac-Studio.local:1234`.
- `llm_client.saw` — since Aug 26 the stage A-C port (one-shot, models +
  auto-pick, streaming); the sections below describing "the first Saw
  attempt" refer to the one-shot-only Aug-12 version it replaced, whose
  findings (DF-215a-e) they document.

Order chosen by the user (Aug 12): get it working in Python first, port second,
debugging the language issues as they surface. The point of writing this down
now is that the first attempt already produced four findings, and they are the
port's real starting material.

## Why this is a good dogfood target

Small, finishable, and it lands on exactly the surfaces design 214 named as
thin — without 214's cost. A Raft simulator is a program; this is an afternoon.

- **A real network client against a real service.** HTTP/1.1 request building,
  a JSON wire format in both directions, a streaming mode, an interactive loop.
- **It is the first thing in the tree that leaves LOOPBACK.** Every net test in
  the suite is `127.0.0.1` or a socketpair. That gap is not academic: it is why
  finding 1 below had gone unnoticed.
- **Its oracle is free** — the real server either answers or it does not, and
  the Python reference beside it makes a differential check possible (same
  prompt, same model, diff the reply path).
- **It is honest about std.json.** The Saw attempt hand-rolls ~150 lines of
  escaping, unescaping and scanning. Design 214 already lists std.json as a
  gap; this is its second independent consumer.

## What the Python reference does (the port's specification)

Standard library only. `/v1/models` + `/v1/chat/completions`.

- one-shot (`llm_client.py "prompt"`), exit 1 with the server's own error detail
  on failure
- `--stream`: server-sent events, tokens printed as they arrive
- interactive REPL keeping conversation history, **vi key bindings** by default
  (`--edit-mode emacs` for the other), plus a persistent history file
- **`--tools`: OpenAI-style tool calling**, with the full round loop —
  request carries the tool schemas, the model answers with `tool_calls`, each is
  dispatched, results go back as `role: "tool"` messages quoting the
  `tool_call_id`, and the loop repeats until the model answers in prose
  (`--max-tool-rounds`, default 6, bounds it). Four read-only tools —
  `get_time`, `calculate`, `list_files`, `read_file` — confined to a tool root
  (`LLM_TOOL_ROOT`, default cwd). Opt-in on purpose, since the file tools grant
  read access to the whole tree. Adding one is a single `@tool`-decorated
  function.
- **`--allow-writes`: a file-EDITING tool** (`replace_lines`, implies
  `--tools`), which replaces an inclusive 1-based line range, deletes one
  (empty content), or inserts at a point (`end_line = start_line - 1`), and
  answers with a unified diff. Gated **twice**: behind the flag (with it off the
  tool is absent from the schemas the model is shown, not merely refused), and
  unconditionally **on the file being tracked by git** — an untracked or ignored
  file is refused before it is even read, and the check FAILS CLOSED, so "git
  is unavailable" also means "no edit". That is what makes the whole feature
  defensible: it converts "everything is in git so nothing can be lost" from an
  assumption into an enforced invariant, and every edit is undoable with
  `git checkout -- <path>`. Writes are atomic (temp file plus rename preserving
  mode, so an interrupt loses the edit rather than the file) and refuse a stale
  line range instead of clamping it — silently editing the wrong lines is the
  one outcome worth refusing outright. There is still no shell and no exec tool.

Three implementation notes the port should not have to rediscover:

- **`git status --porcelain` prints NOTHING for an IGNORED file**, so inferring
  tracking from it reads "ignored" as "tracked and clean" — precisely the false
  reassurance the gate exists to prevent. The tracking question has to be asked
  directly, with `git ls-files --error-unmatch`. (Found because the first
  sandbox lived under gitignored `.build/`.)
- **The calculator is an `ast` walk, not `eval`.** It accepts numbers and
  operators and nothing else, so `os`, `__import__("os").system(...)` and
  `().__class__` are refused as Name / Call / Attribute rather than by a
  blocklist, and the exponent is capped. A tool an LLM drives is the wrong
  place for `eval`, however convenient.
- **Tool failures are returned to the MODEL as the result text**, not raised at
  the user: a bad path or malformed argument JSON comes back as a message the
  model can correct on the next round. Only client-level failures exit non-zero.
  Verified live — the model told the user *why* its untracked-file edit was
  refused.

Coverage: 22 tool-layer cases and 33 edit cases pass, the latter ending with an
end-to-end check that `git checkout -- .` restores every edit the tool made.
- **`--system-prompt FILE`**, plus `--temperature` and `--max-tokens`; the
  system prompt is held APART from the message history rather than at index 0,
  so `/clear` empties the conversation without disturbing it
- **SLASH COMMANDS in the interactive session**, a second name-keyed registry
  built like the tool table: `/model`, `/models`, `/system` (show, set, `@file`,
  `clear`), `/usage` (cumulative and last-turn tokens with tok/s), `/temp`,
  `/max-tokens`, `/tools`, `/stream`, `/history`, `/clear`, `/undo`, `/retry`,
  `/save`, `/load`, `/help`, `/quit`. `//` escapes a literal leading slash.
- `--model` override; with no flag it picks the server's first non-embedding
  model off `/v1/models`, so it runs with no configuration
- `--host` / `--port` / `--timeout`; `LLM_CLIENT_HISTORY` relocates the history
  file

Token accounting is worth one note for the port: the API reports `usage` per
REQUEST, so a tool turn spanning several requests keeps the LAST one (whose
prompt included every tool result), and streaming needs
`stream_options.include_usage` to report at all — LM Studio honours it and
sends a final usage-only frame with an empty `choices` list. It also returns
`completion_tokens_details.reasoning_tokens`, which for gemma is routinely most
of the completion.

Two behaviours the port must reproduce rather than invent. **Tool failures are
returned to the MODEL, not raised at the user** — a bad path, malformed argument
JSON or an unknown tool name comes back as the tool result text, so the model can
correct itself on the next round; only a client-level failure exits non-zero.
And **a failed turn is rolled back wholesale** (mark-and-truncate, not a single
pop): a `tool_calls` message left in history with no matching result makes every
later request invalid, so a half-recorded turn is worse than a dropped one.

`--stream` and `--tools` do not compose and the client says so once instead of
silently dropping one: a tool round has to see the whole message before it can
dispatch. Tools win when both are passed.

One reference-side trap worth keeping in the record because it is invisible
until it bites: **macOS Python is linked against libedit, not GNU readline**,
and libedit ACCEPTS the GNU `set editing-mode vi` spelling without raising and
then ignores it. Try-one-and-catch leaves you in emacs mode with no error
anywhere. The client branches on `readline.backend == "editline"` and issues
libedit's `bind -v`. Proven live under a pty: `abc` ESC `I` `X` yields `Xabc` in
vi mode and `abcX` in emacs, so the modes genuinely differ.

## What the Saw attempt already does

`llm_client.saw` is not a sketch — it works, within its scope (one-shot,
non-streaming). Verified against a local mock server:

- emits **valid JSON** (the mock parses it and echoes the round-tripped prompt)
- unescapes `\n`, `\"`, `\\`, `\uXXXX`, and **surrogate PAIRS** — an emoji in a
  reply decodes correctly, which is the case a naive `\u` reader breaks on
- its **anchored scan** (`"choices"` -> `"message"` -> `"content"`) correctly
  skips a decoy `"content"` key planted earlier in the envelope

## The environment fact that cost the most time

**macOS 15+ gates Local Network access per application.** A binary with no grant
gets `EHOSTUNREACH` (errno 65) from `connect()` for ANY LAN address, while
loopback works normally. A freshly `cc`-built C binary behaves identically, so
this is not std.net and not Saw: `curl` and Python succeed only because they
already hold the grant. The fix is to enable the terminal under
**System Settings > Privacy & Security > Local Network**.

Recorded here because EVERY future net dogfood program on this machine will hit
it, and because it is indistinguishable from a real bug until you know.

## Findings from the Saw attempt — the port's starting material

### DF-215a — std.net cannot name any remote-connect failure — CLOSED (Aug 15)

**What landed.** Both host maps gained the five errnos, under five new SysError
tags: `HostUnreachable` (17), `NetUnreachable` (18), `TimedOut` (19), `HostDown`
(20), `NetDown` (21), with `Other` keeping 16 because the numbers are frozen.
std renders them "host unreachable", "network unreachable", "timed out", "host
is down", "network is down". `examples/net_unroutable_connect_names_the_cause.saw`
is the coverage the second half of this finding asked for — the first test in the
suite that leaves loopback.

**Was widening the tag table an ABI change?** No, and the reading is now written
into rt/ABI.md beside the table: nothing is renumbered, no seam signature moves
(the machine check compares arity and width), a runtime that never returns 17-21
stays correct, and a consumer that does not know them degrades to the text it
printed before, because every tag consumer reads through a total mapping with a
catch-all. The document already named this as the intended mechanism — "diagnostic
richness is instead achieved by mapping the common failure errnos to named tags"
— so the addition is that promise being kept for a program that leaves the
machine, not a new mechanism. SOS's `SosStatus` is a separate contract and is
untouched.

**The `errno()` ruling: renamed to `code()`.** Carrying the real errno needs the
seam to carry it, and the seam deliberately cannot: a failing op returns ONE word
holding its result or `-tag`, which is what maps onto the SOS `(status, value)`
pair, and SOS has no errno to put in it. Adding a second accessor seam would undo
design 117's minimization to buy a number that does not exist on one of the four
intended runtimes. So the fix is the name, and the docstring now states outright
that the value is a portable tag and not an OS errno. The accessor had no callers
in the tree, and the Aug-4 stdlib review had already filed the same rename (M14).

`rt_last_syserror` (`sawc/rt/host_macos/net_os.saw:75-111`) maps sixteen errnos
and omits `EHOSTUNREACH` (65), `ENETUNREACH` (51), `ETIMEDOUT` (60),
`EHOSTDOWN` (64) and `ENETDOWN` (50) — which is to say, **every failure that can
only happen off loopback**. All five collapse to `SysError.Other`, and the user
sees `io error: connect failed (other error)` while the cause sits in `errno`
and is discarded. The suite is 100% loopback and socketpair, which is exactly
why nothing caught it.

Compounding it: **`IoError.errno()` returns the internal `SysError` TAG, not an
OS errno**, despite the name. The Local Network denial above therefore reported
`errno=16`, which reads as a real errno (EBUSY) and is not one. Recovering the
true number needed a scratch probe declaring `socket`/`connect`/`__error`
directly.

This is a "never hide errors" violation in spirit: the cause is available and
thrown away. Fixing the map is small; whether `errno()` should be renamed or
should return the real errno is a ruling.

### DF-215b — `move` of a frame local in a nested block's TAIL is refused in a suspending body

```saw
} else {
    out.append(move chunk)      // refused: the else-block's tail expression
}
```

Reduced to 25 lines. The trigger is the **tail-expression position of a nested
block** inside a driven/spawned function. Ruled OUT as causes, each by probe:
`try` vs `try!`, a `Result` vs non-Result return, and a reference vs by-value
receiver. Adding any statement after the `move` compiles.

That is why the suite never hit it: `examples/net_http_roundtrip.saw` writes the
same `req.append(move chunk)` but follows it with an `if`, so its `move` is not
in tail position.

The diagnostic is also wrong where it matters most — it says *"move it in a
`return` statement instead"*, which does not apply (there is no return in play)
and does not fix it. The workarounds are to add a trailing statement, or to drop
the `move` entirely where the type is ImplicitCopy — which `Data` has been since
design 165, and which is what the landed file does.

### DF-215c — hand-written JSON pays `\{` at every brace

A bare `{` in a string literal opens an interpolation, so
`sb.append("{\"model\":\"")` is not a string containing a brace — it is a lex
error inside an interpolation expression. Every JSON brace must be written
`\{` / `\}`. Correct per the escape rules and clearly documented, but it makes
emitting JSON by hand consistently surprising, and the diagnostic points at the
interpolation rather than at the likely intent. Worth a ruling on the
diagnostic; a std.json encoder would retire the whole question.

### DF-215d — the wrapped `&&` (re-confirmation of DF-172d)

A wrapped boolean condition needs enclosing parentheses; neither line-break
spelling parses. Already filed as DF-172d — logged here only as evidence that
it is hit by a competent reader who had *just read the warning*, which is the
argument for fixing the parse rather than the documentation.

## What the port needs

1. **std.json — and TOOL USE is where hand-rolling stops being viable.** ~150 of
   the Saw attempt's lines are escape/unescape/scan for a *single* string field
   reached by an anchored scan, which works precisely because the client only
   ever wanted `choices[0].message.content`. Tool use needs strictly more than
   that in both directions: EMITTING nested schema objects, and PARSING a
   `tool_calls` ARRAY of objects whose `arguments` field is itself a JSON string
   requiring a second parse. An anchored scan cannot do that — arrays, object
   nesting and per-element extraction are exactly what it traded away. So the
   staging below splits at this line: stages A-C can hand-roll, and the tool
   stage is the one that should wait for a real parser. Third consumer for the
   design-214 gap, and the first that cannot route around it.
2. **Incremental line-oriented reads over a suspending socket**, for `--stream`.
   The attempt reads to EOF, which `Connection: close` makes *correct* but which
   cannot stream by construction.
3. **A line-editing story — the biggest single blocker, and probably its own
   brief.** Saw has no terminal surface at all: no termios, no raw mode, no
   history, no readline. Matching the Python client's interactive mode needs
   either an offloaded libedit/readline FFI or a Saw-native line editor over
   termios. Nothing about this is LLM-specific, which is the argument for
   ruling on it separately.
4. **A read deadline on `TcpStream`** (design 214 item 7): a server that accepts
   and never answers parks the task forever.
5. ~~**DF-215a**, first~~ — LANDED Aug 15. Debugging a network client whose every
   remote failure says "other error" is what made this session long.

`std.env` (argv + variables) and `std.string` were adequate; the one gap there
was a multi-byte `index_of`, which the attempt supplies as a local
`matches_at`/`find_from` pair (`std.string` has `index_of_char` only).

## Staging

- **A — one-shot.** Essentially done; DF-215a landed Aug 15, so failures are
  legible.
- **B — `/v1/models` + model auto-pick.** Needs array scanning, or std.json.
- **C — streaming.** Needs item 2.
- **D — TOOL USE.** The stage that wants std.json for real (item 1). Also wants
  a dispatch table over heterogeneous handlers — `Map<String, ...>` of closures
  or of an `any Tool` existential, which is itself worth knowing about, since a
  registry of behaviours keyed by name is a shape the language has not been
  pushed on yet. Independent of E below, and more valuable: tool use is the
  interesting half of a modern client, line editing is table stakes.
  The WRITE half additionally needs `std.process` (to shell out to git for the
  tracking gate) and an atomic-replace idiom over `std.file` — there is no
  `rename` + mode-preservation helper in std today, and `File.rename` exists
  while `chmod`/`stat` do not, so the Saw port cannot yet reproduce the
  mode-preserving atomic write without new surface. Worth a probe before D is
  scheduled.
- **E — interactive.** Blocked on item 3; likely a separate brief.
- **F — dispose of the reference.** Either delete it, or keep it as a
  differential oracle. Deciding that is part of F, not before it.

## Open questions

- Is the Python reference a permanent differential oracle or a scaffold to
  delete once D lands?
- Does the line-editing gap (item 3) get its own design, and does it aim at FFI
  or at a native termios implementation?
- Does 215 wait for std.json or hand-roll it? The attempt proves hand-rolling
  works; the question is whether a second hand-rolled JSON codec in the tree is
  a cost worth paying to keep the port unblocked.
- ~~Should `IoError.errno()` be renamed, or return the real OS errno with the tag
  exposed separately?~~ ANSWERED Aug 15: renamed to `code()`. The raw errno cannot
  reach std without a new seam, and the one-word status convention is what makes
  the ABI fit SOS — see the DF-215a section.

## The stage A-C rewrite (Aug 26)

A dogfood agent (design 203 instrument, Sonnet, docs-only knowledge) rewrote
`llm_client.saw` from scratch against the current language — the Aug-12
attempt had bit-rotted at design 234's allocator flip (every bare `append`
became a discarded-Result compile error). What landed: one-shot chat,
`--list-models`, non-embedding auto-pick, `--stream` with each SSE delta
printed as its HTTP chunk is read off the socket (both body framings:
Content-Length and an incremental chunked decoder), `--system-prompt` /
`--temperature` / `--max-tokens`, hand-rolled JSON both directions with
surrogate-pair unescaping. Stage D (tools) and E (interactive) stayed out of
scope per this brief's staging: std.json and the terminal surface.

Verified against a loopback mock with planted traps, all passing: a decoy
`"content"` key before `choices` is not mistaken for the reply; an escaped
emoji surrogate pair and embedded `\n` decode exactly; the embedding-first
model list is not auto-picked; SSE frames sent 0.4s apart print with ~0.4s
gaps (timestamped subprocess capture — genuinely incremental, not
read-to-EOF); a 400 exits nonzero quoting the server's JSON detail verbatim;
connection-refused exits nonzero with a legible line (via `try!` panic —
DF-215f's debt, see below).

### DF-215f — the soundness finding (and why the client carries a workaround)

The agent's designed error handling — `match` each suspending `TcpStream`
op's Result into a `ClientError` — corrupted the moved-out payloads. Reduced
to a deterministic no-network repro and then to a five-row trigger matrix,
each row removing one leg (lead-verified on main, Aug 26):

| row | suspending callee | `match` + `move`-out | value leaves the fn | result |
|---|---|---|---|---|
| tail auto-wrap | yes | yes | yes | CORRUPTS |
| bind + `return move` | yes | yes | yes | CORRUPTS |
| local use only | yes | yes | no | clean |
| `try` propagation | yes | no | yes | clean |
| sync callee | no | yes | yes | clean |

Manifestation varies by payload (Arc refcount underflow panic, early deinit,
SIGSEGV, a `TcpStream` that reads back as a broken socket) but the divergence
is deterministic run-to-run with an Arc-instrumented payload, which is what
the pin uses: `examples/coro_match_moved_payload_survives_return.saw` (XFAIL,
the five rows above). Suspected mechanism family: DF-218w/DF-242a — the
container-head hoist parks the scrutinee in a frame temp and the frame's
release does not know an arm moved the payload out. The obligation-4 sweep
owes the enumeration of every frame home a moved-from value can still be
released from before the fix dispatches.

The landed client's workaround: every suspending TcpStream op unwraps with
`try!` (which does not trigger the bug), so a connect failure panics with the
IoError message instead of returning the designed ClientError. The fix
restores the match spelling — the site comment in the client says so.

### The smaller findings

- **DF-215g** — `find_thing(5) == None` refuses ("cannot tell what this
  `None` is a `None` OF") though the call's return type fully determines it;
  the annotated-local twin compiles. Probe kept at
  `.build/scratch/probe_none_eq_call.saw` shape (six lines).
- **DF-215h** — no newline-free stdout write anywhere in std, so the
  `--stream` deltas print one per line; any progress-style output hits this.
- **DF-215i** — no boolean `guard cond else { }`; the agent reached for it
  first for bounds checks.
- **DF-215j** — `return` in a value match arm: "Unexpected token: RETURN"
  with no hint that arms are expressions (brace it, or drop the `return` for
  auto-wrap); the agent chased the brace fix before finding the idiom.
- **DF-215c re-hit verbatim** — the fresh reader's FIRST compile error was
  the JSON `\{` brace escape, in a plain literal with no interpolation in it.
  Evidence for fixing the diagnostic, exactly as the DF predicted.
- Docs: `byte_at`'s `Int8` return was stated only via a parenthetical on
  `bytes()` (spec fixed on discovery, Aug 26 — the agent wrote ~25
  `u8`-literal comparisons first); no doc enumerates std method signatures,
  so several surfaces (`Data.append` overloads, `Env.args()` argv[0]) were
  discovered through compiler diagnostics — open docs question, `--emit-docs`
  may be the answer.
- Pleasant (calibration): `Data.slice`'s O(1) CoW windows made the rolling
  network buffer allocation-free by hand-off; `try` + auto-wrap composed
  cleanly through four levels of `Result<_, ClientError>`; `chars()` +
  `append_scalar` round-tripped UTF-8 byte-for-byte with no special-casing.
