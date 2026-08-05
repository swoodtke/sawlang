# Design 136 — `unsafe` moves to the declaration effect slot

STATUS: APPROVED (user, Aug 5). Sequenced immediately after 131 integrates
and BEFORE 132 (it re-spells every unsafe declaration, so it must run with
the tree to itself; it is mechanical and fast). Restores the original
design-130 [user] decision — "effect position beside `sync`" — which 130's
agent had to interpret against the brief's own contradictory examples.

## The rule

A declaration's signature reads IDENTICALLY to its function type. `sync`
already sits in the post-parameter effect slot on declarations
(`func resume(&var self) sync -> __Poll`, builtin.saw); `unsafe` joins it
there, with the slot order matching the type grammar (`unsafe sync
escaping`):

```saw
func with_var_ref<R>(&var self, i: Int, body: (&var T) sync -> R) unsafe -> R
//                                                              ^^^^^^ was: unsafe func ...
```

- Prefix `unsafe func` / `unsafe init` becomes a clean parse error with a
  fixit naming the slot position (mirror of what 130 did for the opposite
  spelling — flip the accepted/rejected sides).
- **`unsafe struct` stays prefix** [decided with option 1]: a struct
  declaration has no signature slot, and the enforced `Unsafe*` name
  carries the visibility. Document the asymmetry in one spec sentence.
- Function TYPES are unchanged (`(T) unsafe sync -> R` — already the slot).
- `--emit-docs` output and any diagnostics that print signatures render the
  slot spelling.

## The sweep

Re-spell every migrated declaration — 130 counted 262 `unsafe` funcs/inits
(std 136, rt 47, examples 59+10, blade 5, sos 5) — plus any 131 added.
Mechanical; no semantic change; irdet/astdiff must be byte-identical on IR
(spelling only). lexdiff parity: the LEXER is untouched (`unsafe` is
already a keyword token; position is a parser concern).

## Tests
Slot spelling accepted on func/init (incl. combined `unsafe sync` order and
a suspending unsafe function); prefix spelling errors with the fixit;
`unsafe struct` still prefix; a signature-printing diagnostic and
`--emit-docs` show the slot form; the design-130 regression tests re-spelled
and green. Full gate battery (suite, lexdiff, irdet, astdiff, bootstrap,
sos).

## Docs
LANGUAGE_SPEC.md unsafe section + grammar line; saw-lang skill digest;
README examples if any show unsafe signatures. Tracker: one line under 130's
entry noting the spelling correction landed as 136.
