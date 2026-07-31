# Design 84 — Safe net API: TcpListener/TcpStream owning types (DECIDED Jul 31)

**Ruling (user):** public APIs must NEVER expose raw fds or raw
pointers. std.net's current free-functions-over-`Int`-fd +
`UnsafePointer` buffers force application code (the httpd dogfood)
into `unsafe` and allow fd double-close/leak. Replace with owning
socket TYPES + safe buffers; the fd and all pointers live INSIDE
std.net's marked domain.

## The shape (pinned)
- **`TcpListener`** (NoCopy; wraps the listen fd; `Deinit` closes it):
  - static `listen(port: Int) -> Result<TcpListener, IoError>`
  - `local_port(&self) -> Int`
  - `accept(&self) -> TcpStream` — COOPERATIVE SUSPENDING: parks on
    the listen fd internally (io_wait hidden) until a connection,
    returns the owned stream. (Cancellation-observing at the park,
    per design 76 A3.)
- **`TcpStream`** (NoCopy; wraps the conn fd; `Deinit` closes it):
  - static `connect(host: String, port: Int) -> Result<TcpStream, IoError>`
    (suspending: parks until connected)
  - `read(&self, into: &var Data) -> Int` — suspending; appends up to
    an internal chunk of bytes to `into`; returns count read (0 =
    peer closed); parks internally on would-block.
  - `write_all(&self, bytes: &Data) -> Result<Void, IoError>` and
    `write_all_str(&self, s: String)` (overload if the sig allows,
    else the two names) — suspending; writes the WHOLE buffer,
    parking on would-block until done.
  - (`&self` is fine — the fd is just read; internal state, if any,
    is behind the resource. Use `&var self` only if an internal
    read buffer demands it — report.)
- **`IoError`** conforms to `Error` (design 56) — errno-shaped, with a
  Printable message; carries the failing syscall + errno.
- Suspension is ENTIRELY hidden inside the methods (no `io_wait` /
  `net_would_block` / `net_buffer` in application code). A worker
  becomes: `let s = listener.accept(); handle(s)` — no unsafe, no
  pointers, no fds.
- The raw layer (the existing `tcp_*`/`net_*` free fns + externs)
  becomes PRIVATE to std.net (module-private after design 80/82;
  marker-carrying inside the marked domain). Keep them as the
  implementation; do NOT expose.

## Scope
1. Implement the types in std/net.saw over the existing raw layer;
   fd stored as a private field (raw-pointer-free — fd is an `Int32`).
   Deinit calls close exactly once (NoCopy = no double-close; the
   move checkpoint prevents use-after-close). accept/read/connect
   park via the internal io_wait — VERIFY a suspending METHOD called
   from a spawned worker body drives correctly (design 45 0c + design
   83 tail/statement nesting; this is the load-bearing interaction —
   test it explicitly).
2. `Data` read target: confirm/extend `Data` has an append-bytes-from-
   a-pointer internal path (std.net fills it); `Data.to_string()` for
   text. If Data lacks a grow/append primitive, add it (private-ish)
   — report.
3. **Migrate `.build/scratch/httpd_sw.saw`** to the new API as the
   acceptance dogfood: it must compile with ZERO `unsafe`, ZERO raw
   fds/pointers, and reach codegen. Move the cleaned httpd into
   `examples/` or a blade-test if it makes a good permanent smoke
   (report; a socketpair/loopback echo test is the deterministic
   version for the suite — no bound ports in CI).
4. Tests (loopback/socketpair only, deterministic, time-bounded): a
   TaskGroup echo server + client round-trip through TcpListener/
   TcpStream (accept/read/write_all), peer-close → read returns 0,
   Deinit-closes exactly once (fd-leak probe: open+drop N, no fd
   exhaustion), connect-failure → IoError, suspending-method-from-
   spawned-worker drive. Keep the existing net_* tests green (or
   migrate them; the raw layer stays, now private).
5. Docs: spec net section (the owning-types model; raw layer is
   internal), saw-lang skill (net gotchas → the safe pattern; remove
   any raw-fd/pointer guidance), tracker (design 84 landed; the
   leaky-pointer/raw-fd API issue CLOSED).

## Hazards
- Suspending method + internal io_wait from a spawned/driven body is
  THE risk — design 83 just fixed tail/statement nested suspends;
  a method that suspends internally, called as a statement in a
  worker loop, is exactly that shape. Test first; if the transform
  still gaps on it, that's a fix-on-discovery coroutine item, not a
  reason to expose io_wait.
- Deinit-close vs a stream MOVED into a handler / returned from
  accept: exactly-once close across the move (the NoCopy + drop-flag
  machinery); fd-leak exact-count test.
- read appending to a caller `&var Data` across a suspension: the
  Data borrow is held across io_wait — ensure the borrow/exclusivity
  rules allow it (Data is the caller's, parked frame holds the &var)
  and no double-free of Data on the suspend path.
Bars: full suite (baseline 868) + blade/libs + bootstrap green per
commit; zero xfails. Standing policy; interruption-safe commits;
saw-lang skill self-review.
