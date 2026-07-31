# Design 82 — Close the std visibility gap: per-file std modules (DECIDED Jul 31)

**Ruling (user):** retire design 80's std-as-one-module deviation —
it invites accidental (or lazy) invariant abuse by future std code.
std files become ordinary modules to EACH OTHER; genuinely shared
internals are marked **`public(package)`** (std is the package), so
intentional sharing is explicit and `Vector.length` becomes invisible
even to channel.saw.

## Scope
1. Flip the visibility module-identity for std from single-module to
   per-file (the design-80 machinery already keys on source file —
   remove the std coalescing special case; ACCESS checks only,
   codegen/compiler-known-ness untouched).
2. Sweep the ~182 std-internal cross-references design 80 counted:
   most become `public`/`public(package)` on the API they already
   were; true internals that another std file touches get
   `public(package)` ONLY if the sharing is legitimate — otherwise
   restructure the toucher to go through the owning module's API
   (report each restructure; that list is the abuse audit).
3. Synthesized-access provenance exemption unchanged.
4. Tests: a std-internal privacy probe (compile a scratch std-like
   module pair? — if std privacy isn't harness-expressible, assert
   via the compiler's own suite staying green + a tracker note on
   the enforcement path), plus the existing visibility family.
5. Docs: spec note (std has no special visibility status), tracker
   (design 80 deviation retired, design 82 landed).

Bars: full suite (baseline = post-81) + blade/libs + bootstrap green
per commit; zero xfails. Mechanical but wide — the suite is the
oracle. Standing policy; interruption-safe commits; saw-lang skill
self-review.
