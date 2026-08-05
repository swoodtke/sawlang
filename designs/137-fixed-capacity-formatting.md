# Design 137 — fixed-capacity formatting: alloc-free panic, assert, and print

STATUS: APPROVED (user, Aug 5). Sequenced BEFORE 135 (pipeline ... → 134 →
137 → 135) so the `--no-hidden-alloc` flag lands with the good spelling
already available and its errors can point here; std-only + small compiler
surface, may be pulled earlier if a slot opens.

## Goal

A formatting path with ZERO heap allocation, end to end, so that:
- `panic` / `assert` can assemble a real message under allocator
  exhaustion, freestanding, and under the 135 flag (today `panic(msg)`
  assembles into a fresh allocation — design 123 needed a deny WINDOW
  around exactly this);
- the kernel gets alloc-free `print`/logging `[user]` — SOS log lines
  stream to the console seam without touching the allocator;
- the 135 ban stays uniform as decided: interpolation PRODUCING A HEAP
  STRING remains banned under the flag everywhere; the fixed path is not a
  carve-out because no allocation occurs.

## What already exists (the leverage)

`Printable.format(&self, into: &var StringBuilder)` is ALREADY streaming,
and interpolation already lowers through it with no intermediate Strings.
String literals are immortal statics (no allocation). The ONLY heap in the
whole story is StringBuilder's growable buffer. Replace that one thing.

## Design

1. **A fixed-capacity builder mode.** PREFERRED MECHANISM: StringBuilder
   itself gains a fixed mode over caller-provided or stack storage whose
   grow path TRUNCATES instead of reallocating — `Printable.format`'s
   signature is untouched and every existing conformance composes. (123
   already routed growth through a private `_reserve -> Bool`, so the
   fixed mode is a second answer to "reserve failed".) Truncation is
   MARKED (trailing `…`/`+` byte) — never-hide-errors applies to cut
   messages too. PROBE the storage question honestly: inline fixed storage
   wants a value-generic capacity (`FixedStringBuilder<N>` — design 108
   default-value machinery may or may not stretch to this); a
   caller-provided `&var [UInt8; N]` wants slice-shaped plumbing (G3 is
   not built). If both fight the current language, a small set of concrete
   capacities or a compiler-known scratch shape is an acceptable v1 —
   record the choice and the pain as DF-findings per the no-workarounds
   policy; do NOT contort the generics model from inside this brief.
2. **panic/assert format into fixed storage.** Their implementations
   assemble into a stack scratch buffer (per-task/per-thread by
   construction — a stack array; never a shared static, MT groups exist)
   and write via the panic seam. Bounded messages truncate with the
   marker; the design-122 `panic at FILE:LINE:` interned prefix is
   unchanged. The 123 deny-window hack becomes unnecessary — remove it if
   the tests confirm.
3. **Typed format-arg overloads, not varargs.** `[user: printf-style
   ergonomics]` `panic("panic: {}", reason)` via monomorphized generics —
   `panic<A: Printable>(fmt, a)` up through a few arities (pick with the
   overload machinery; labeled args if it reads better), `{}` positional
   placeholders, arity/placeholder mismatch is a compile error. Same
   family for `assert` and **`print`** `[user]` — `print("x = {}", x)`
   streams each argument through its `format` into fixed storage (or
   chunk-writes to the output seam) and never allocates.
4. **Freestanding dogfood.** SOS kernel logging moves onto the alloc-free
   print path; the 135 gate then proves it stays clean.

## Tests
Fail-before/pass-after: a panic message assembled under
`__saw_rt_alloc_deny_after` full denial (no window) reports the RIGHT
message; truncation marker on overflow; format-arg overloads typecheck
(mismatched arity/placeholder count is a compile error test); print
overloads produce identical output to the interpolation spelling for the
same values; SOS kernel log line via the new path under QEMU; full gate
battery.

## Docs
Spec (Printable/StringBuilder + panic sections), saw-lang skill, README
(the kernel-logging story is audience-facing; saw-docs voice). Tracker:
note 123's deny-window removal if it happens; DF-findings for any
generics/slice pain hit in unit 1.
