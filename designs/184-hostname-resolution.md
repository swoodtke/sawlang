# Design 184 — hostname resolution, offloaded from day one

**Status: APPROVED direction (user, Aug 8). Closes DF-181d (connect ignores
its host). DEPENDS ON design 183 (offload v2) being green on main — this is
its first real consumer and the proof the machinery earns its keep. The
audit's warning is the design law here: resolution must NEVER exist as a
naked seam.**

## Units

1. **The literal fast path, in Saw.** Dotted-quad IPv4 parse (pure string →
   big-endian u32, prompt, no libc); a literal host never touches the
   resolver or leaves the executor thread. This alone kills the
   wrong-dial-loopback bug for every literal caller.
2. **The seam**: a flattened, offload-shaped resolver wrapper —
   `__saw_rt_resolve_ipv4(host: UnsafePointer<Int8>, out: UnsafePointer<UInt32>, max: Int) -> Int`
   (count resolved, or -tag) — implemented over getaddrinfo(AF_INET) +
   freeaddrinfo in the rt Saw/shim layer, declared `extern blocking`, and
   OFFLOADED via 183's machinery. The host bytes and the out-buffer live in
   the suspended frame per 183's pointer rule. rt/ABI.md entry states the
   blocking contract explicitly (the first seam that says so — the 181
   audit's documentation standard).
3. **The connect path rewires**: `TcpStream.connect(host, port)` = literal?
   direct dial : resolve (offloaded, siblings run) then dial the first
   result. The seam widens to carry the address
   (`__saw_rt_tcp_connect_start(addr_be, port)` — mechanical ABI.md
   change); the hardcoded loopback_sockaddr dies. A resolution failure is
   an `Err(IoError)` naming the host; an empty result likewise. Starvation
   test: sibling ticks while a slow resolve is in flight (a controllable
   fake — resolve a name via a hosts-style injection or accept a
   timing-loose pin; NEVER a flaky network-dependent test in the suite).
4. **Docs**: net docs state resolution's threading story plainly; skill
   updates the connect idiom. Tracker: DF-181d closed; future-work notes —
   IPv6/happy-eyeballs (needs the dual-stack design), resolver caching,
   Command-env-style hosts injection for tests.

## Explicitly out

IPv6 and happy-eyeballs; caching; a from-scratch DNS client (rejected —
platform resolver semantics live in getaddrinfo; every serious runtime
ends up here); resolv.conf parsing; timeouts beyond the OS resolver's own
(a Duration-taking connect timeout is a future net design over 180's
vocabulary).
