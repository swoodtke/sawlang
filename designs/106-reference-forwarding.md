# Design 106 — reference forwarding: pass a received `&T`/`&var T` onward (queued Aug 2)

Final pre-SOS batch, part 5 of 6. The design-96 flag: inside
`func f(r: &var Data)`, calling `g(&var r)` (or `g(&r)`) is
impossible — the reference param auto-derefs to its value (NoCopy/
type error), which forced read_into to route through methods instead
of helpers. Forwarding is natural and SAFE (the callee's borrow is
non-escaping and strictly nested inside the caller's).

DECISION MADE WITHOUT THE USER (review tomorrow): allow forwarding as
a RE-BORROW with these rules —
- Call-site spelling stays mirrored: `g(&r)` / `g(&var r)` where `r`
  is a reference param in scope (the sigil names the borrow the callee
  gets, same as for locals; bare `r` in value position keeps meaning
  the referent value — no silent change).
- `&var` forwarding requires the incoming ref to be `&var` (no
  upgrade); `&var` may forward as `&` (downgrade fine).
- Law of Exclusivity: the forwarded borrow is a re-borrow of the SAME
  root path — the existing overlapping-path checks apply with the
  param's referent as the path root; while forwarded, the original
  ref param is inactive for conflicting uses within that call
  expression (standard nested-borrow rule; statically checkable at
  the call site since references never escape).
- References still cannot escape, be stored, or span into spawned
  tasks (designs 80/88 rules unchanged); a forwarded ref held across
  a suspend in a DRIVEN callee frame follows design 88 (frame-
  resident pointer, never dropped).
- `&self` methods: `self` forwards under the same rules
  (`g(&self.field)` projection-forwarding is IN scope if it falls out
  of the path machinery; flag it out if disproportionate).

## Implementation
Typechecker: accept a reference param as the operand of `&`/`&var` at
call sites (today only bindings qualify); exclusivity path = the
param's root. Codegen: pass the already-held pointer through (no
re-take of an address of a local slot; the design-88 frame-resident
case already stores the pointer — forward THAT). Coro: a forwarding
call inside a suspending body embeds per the normal rules (the
pointer is a frame field — design 88 machinery).

## Tests
Forward `&` and `&var` one level and two levels (f->g->h); mutation
through a twice-forwarded `&var` visible at the root caller;
exclusivity violation via forwarding (clean error: `&var r` forwarded
while `r`'s referent also passed `&` in the same call) — exact
positions; `&`->`&var` upgrade rejected; forwarding across a suspend
in a driven callee (value visible after resume); re-simplify
read_into's method-routing workaround in std/net.saw to direct
helper forwarding as the acceptance (design-96 flag closed).

Bars: full suite (zero xfails) + bootstrap (incl. libs) green per
commit. Standing policy; foreground; watchdog; interruption-safe;
skill self-review; docs = spec references section + skill + tracker.
