# Design 92 — Failable calls return Result: no silent error swallow (DECIDED Aug 1)

**Ruling (user):** any operation that can fail must SURFACE the failure
(`Result<T, E>`, or `T?` for uninteresting failures) — never a `Void`
return that drops the error, and never a sentinel indistinguishable
from valid data. Motivated by design 90: `write_all`/`write_all_str`
returned `Void` and silently swallowed a hard write error, which
MASKED the connect bug for an entire session. Std-wide audit + fix.
Land AFTER design 89-b (it changes `net.saw` signatures the 89-b
worktree acceptance uses — avoid the cherry-pick conflict).

## The principle (document in the skill + spec)
- Fallible → `Result<T, IoError/…>` (the caller must handle or `try`).
- Uninteresting-failure → `T?` (parse-style).
- NEVER a `Void` return that hides a failure; NEVER a sentinel that
  collides with a valid value (e.g. empty `Data` meaning BOTH EOF and
  error).

## Audit + fix (std io/net/file/process, the whole failable surface)
1. **net (the known offender):** `TcpStream.write_all` /
   `write_all_str` → `Result<Void, IoError>`; `read` → distinguish
   EOF from error (today empty `Data` = peer-close; an ERROR must be
   distinct — either `read(&…) -> Result<Int, IoError>` returning 0
   for EOF, or a `ReadOutcome`; pick and report — the value-based
   `read() -> Data` can't express error, so this likely changes the
   read signature). `accept`/`connect` already Result-ish — verify.
2. **file/directory/path:** every open/read/write/seek/mkdir/remove
   that can fail — audit for Void-or-sentinel swallow; convert.
3. **process:** run/output error paths (design 59 fixed the exit-code
   decode; verify no swallow remains).
4. **env / others:** sweep for the pattern.
5. Migrate all callers (std internals, blade, libs, examples, tests)
   to handle/`try` the new Results; the httpd/echo tests thread the
   errors. `blade` is a heavy consumer — its io/process error handling
   tightens (good dogfood).
6. Report the FULL list of functions changed + any that legitimately
   stay `Void`/`T?` (a genuinely-infallible op, or one where `T?` is
   the honest shape).

## Concrete findings (Aug 1 std scan — the checklist)
TIER 1 (true hide — fix all):
- `net.TcpStream.write_all` / `write_all_str` → **collapse to a single
  overloaded `write`** (user, Aug 1): `write(bytes: Data) ->
  Result<Void, IoError>` + `write(s: String) -> Result<Void, IoError>`
  (design-55 overload — distinct types). It IMPLICITLY writes the
  WHOLE buffer (loops + parks internally, as write_all does today) and
  returns the error honestly. REMOVE `write_all`/`write_all_str` (no
  deprecated alias — pre-1.0). NO public partial/short `write` — the
  raw single-syscall write stays the PRIVATE extern. Migrate all
  callers (httpd/echo/tests) to `write` + handle/`try` the Result.
- `net.TcpStream.read() -> Data` → error must be distinct from EOF
  (empty Data currently = BOTH). Pick: `read(&var Data) -> Result<Int,
  IoError>` (0 = EOF) or a ReadOutcome; report.
- `net.TcpListener.accept() -> TcpStream` → `Result<TcpStream,
  IoError>` — currently NO error channel (a failed accept can only
  return a broken/invalid-fd stream). **(scan-added)**
- `process.Command.run() -> Int32` → `Result<Int32, ProcessError>`
  (Ok(code) = exited-with-code; Err = couldn't launch) — currently
  conflates system()=-1 "couldn't run" with a real exit code.
  **(scan-added)**
TIER 2 (`Bool`-hides-why — real error indistinguishable from an
expected `false`, cause lost; convert to `Result<Void, IoError>`,
keeping a genuine boolean question like `exists` as `Bool`):
- file: `remove`, `rename`
- directory: `create`, `remove`, `set_current`
- env: `set`, `unset`, `set_cwd`
LEAVE AS-IS (not hiding — confirm, don't change): `data.push`/`append`
etc. (`Void`; failure is an OOM PANIC = surfaced loudly);
`Path.parent`/`ext`/`stem`/`file_name` (`T?` for genuinely-absent
components); `exists`-style boolean QUESTIONS. Lower-priority/borderline
(report, fix if cheap): `file.write`/`seek` return `Int?` (surfaces
failure but loses the errno cause — Result would be richer).

## Tests
Each converted function: a success path + a forced-failure path
asserting the error is RETURNED not swallowed (e.g. write to a closed
fd → `Err(IoError)`, not silent success; read error distinct from
EOF). Regression: the whole net/file/process suite green under the new
signatures.

## Docs
saw-lang skill (the failable-returns-Result principle + the net/io
signatures); spec (io/net error model); CLAUDE.md digest if it names
any changed signature; tracker (design 92 landed; the design-90
write_all swallow flag closed).

Bars: full suite (baseline = post-91) + blade/libs + bootstrap green
per commit; zero xfails. Standing policy; interruption-safe (commit
per module: net, then file, then process, …); saw-lang skill
self-review.
