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
