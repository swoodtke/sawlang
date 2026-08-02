# Design 95 — Driven-method frames keyed by resolved signature (queued Aug 2)

Coroutine-transform limitation surfaced by design 92: a driven
(spawned/__drive'd) suspending METHOD is keyed by `(struct,
method-name)` when its frame is synthesized/embedded, so two OVERLOADS
of the same method name mis-resolve to ONE frame. This forced design
92 to ship a single `write(bytes: Data)` (text callers do
`s.to_data()`) instead of the intended `write(bytes: Data)` +
`write(s: String)` overload pair.

## Scope
1. Key driven-method frame synthesis/embedding by the RESOLVED
   signature (the design-55 resolved callee — its param-type mangling
   / `$OL$`+`$LB$` key), not `(struct, method-name)`. So overloaded
   suspending methods each get their own frame and drive correctly.
2. Re-add `net.TcpStream.write(s: String) -> Result<Void, IoError>`
   as the overload of `write(bytes: Data)` (writes the whole string's
   bytes); revert the `s.to_data()` workarounds at call sites (httpd/
   echo/tests) to `write(s)`.
3. Tests: a spawned/driven worker calling each of two same-named
   suspending method overloads (Data + String) round-trips both
   (distinct frames, no mis-resolution); the design-92 net suite +
   accept-loop stay green.
4. Docs: saw-lang skill (the `write` overload is back; note driven
   overloaded methods work); tracker (design 95 landed; the design-92
   write-String deferral closed).

## Hazards
- The frame key is used in several places (synthesis, embedding,
  __recv, the design-84 method-embedding, design-70 effect monos) —
  change it in ONE canonical spot; the coro_*/taskgroup_*/net_*
  families are the oracle.
- Don't regress non-overloaded driven methods (the common case) —
  their key is unchanged in effect (one signature per name).
Bars: full suite (baseline = post-94) + blade/libs + bootstrap green
per commit; zero xfails. Standing policy; foreground suites;
interruption-safe; saw-lang skill self-review.
