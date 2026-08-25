# Design 243 — trailing-brace call syntax (BACKLOG scoping brief)

**Status: AUTHORED Aug 24 2026 (lead, from the design-242 unit-3
conversation); BACKLOGGED by the user same day — "maybe not right now but we
should brief it; it's a nice usability win." No rulings made; the questions
below are the brief's content.** (The DF-243* findings predate this brief
and are unrelated — they are the sos-riders' range.)

## The proposal

A call's final closure argument may be written AFTER the argument list:

```saw
Task.spawn(priority: 3) { [p1, p2] in ... }
// today's spelling:
Task.spawn({ [p1, p2] in ... }, priority: 3)   // closure as an ordinary arg
```

Motivated by the design-242 spawn braces, where the body is the point of the
statement and burying it inside the parentheses ahead of its configuration
reads backwards. General usability win anywhere a trailing closure is the
"body" of a call (`v.map`, `with_ref`, `Mutex.lock`, the spawn family).

## Why this is a DOCTRINE decision, not a parser feature

Saw has deliberately NO trailing-closure syntax: a closure is an ordinary
argument, and several load-bearing rules lean on that uniformity —

1. **`{}` newline significance** (design 129): a `{` after a completed call
   expression currently ends the statement's expression cleanly; a block or
   closure literal in statement position is design 122's "never called"
   error. Trailing braces give `f(a)\n{ ... }`-adjacent shapes a second
   reading, and the disambiguation rule (same line only? no newline before
   `{`?) becomes part of the grammar contract.
2. **Argument-position uniformity**: labeled-argument mapping (design 105),
   overload resolution (55), and the closure-parameter effect checks all
   assume the closure sits IN the argument list. A trailing brace is
   sugar mapping onto "the last parameter of closure type" — which needs a
   rule for overload sets where candidates DISAGREE about the last
   parameter, and for calls with TWO closure parameters.
3. **The precedent cost**: the grammar has refused position-specific sugar
   consistently (no `unsafe` blocks, no trailing `<>` commas, the binary
   operators do not wrap). Granting one exception invites the next; the
   brief should say why THIS one clears the bar (the body-is-the-point
   argument) if it does.

## Scope question (the main ruling, deferred)

- **(A) Spawn-family only** — `Thread.spawn` / `Task.spawn` / `group.spawn`
  get the trailing form as part of their own grammar (they are already
  special-ish: `Thread.spawn { }` parses today). Smallest surface, weakest
  precedent damage, but "why only spawns" needs an answer in the docs.
- **(B) General** — any call whose final parameter is closure-typed. The
  real usability win (`v.map(...) { ... }`, `lock { ... }`), the full
  doctrine cost. Swift's experience (trailing closures + multiple trailing
  closures) is the case study to read before ruling.

## Interactions to spec before any ruling

- The design-242 spawn-brace rule (explicit capture lists) composes
  unchanged — the trailing brace is position sugar, the list rule is about
  the closure's own header.
- `#lend_var` / `borrows` bodies, `-W` warning positions, and the
  statement-tail Result-discard rule all read "the call expression" — the
  trailing brace must be INSIDE the call's extent for all of them.
- Formatting/lexdiff/astdiff: the dumper shows the authored form; a
  parser-level sugar must decide what the AST records (design 218's
  astdiff note: the authored form is the contract).

## Disposition

Sits in [BACKLOG] until the user pulls it. When pulled: rule the scope
question first, then a small unit (parser + the disambiguation rule +
overload interaction + docs), with design 129's newline matrix extended as
the test plan.
