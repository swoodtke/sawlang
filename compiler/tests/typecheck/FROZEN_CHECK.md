# The one-time check against the frozen compiler

The record of `frozen_check.py`, run once for SL-447's U6b1 and again for its
U6b2 and U6b3, and of `frozen_effects.py`, run once for U6b3. The frozen
compiler's answers are checked and recorded here; they are never the
definition of what typecheck must answer.

## Exhaustiveness, discarded Results and suspension (U6b3, `frozen_effects.py`)

- **The sawc2 build.** The frozen compiler builds it, so by its rules every
  `match` in it is exhaustive and no `Result` in it is discarded. sawc2 checks
  196 `match` expressions over the build's own modules and refuses none, and
  refuses no discarded `Result`.
- **The corpus's refusal programs for the two rules**, whose expected error
  names a non-exhaustive match or a discarded `Result`: 9 programs, 8 refused
  by sawc2's matching rule (2 `match.non-exhaustive`, 6 `result.discarded`,
  the statement, match-arm, positions, erased, suspending and `try!`-payload
  cases). The ninth, `try_catch_union_nonexhaustive_error.saw`, is a
  `try ... catch` block, which sawc2 refuses first as `slice.not-yet`.
- **The suspension sample**: the 34 corpus programs that park through
  `yield_now` and use nothing outside the sync-only slice, none of them
  expecting a refusal. sawc2 checks 26 with no refusal (5 are `slice.not-yet`
  first, 2 `import.unknown-module`, 1 `visibility.private`), and the frozen
  compiler rejects one of those 26. Over the other 25, **93 functions the
  frozen coroutine transform frames are may-suspend in sawc2**, and none it
  frames is never-suspends there; no function sawc2 finds may-suspend is left
  unframed by the frozen ledger.

The frozen side is the frame ledger (`--emit-frame-ledger`): a function counts
as framed when its FRAME row says `boundary=yes`, or, for a generic method
template, which owns no frame, when an instance of it is framed. Free
functions are compared by name (`name$m$module` loses its module), methods as
`Type.method` (`Type_method` in the ledger), and rows homed in std are left
out, as sawc2 summarizes std from its table.

`frozen_check.py` was run again over the build as it stands after U6b3, its
per-path use count included, with the summary each function's dump now
carries left out of the comparison: 611 field types, 1564 signatures and 118
Copy tiers agree, and 5846 binding types, 11485 receivers, 266
instantiations, 1493 overloads and 1369 modules, with no difference.
`frozen_effects.py`, run again on the same build, gives the answers above.

## Bodies: call targets, instantiations and binding types (U6b2)

Over the sawc2 build as it stood when U6b2's literal arms and static peers
were fixed (D17), the driver and the lex, parse, resolve and typecheck
packages, the typecheck package's body half included:

- **5070 `let` and `var` binding types agree**, by file, line and name, and
  none differs.
- **10230 receiver types agree**, each method call's receiver as the frozen
  compiler annotates it against the type sawc2 instantiates the method at,
  and none differs.
- **1259 overload choices agree**: each call of an overloaded method, which
  in this build is `StringBuilder.append` for `String`, `Int` and `Byte`, by
  the parameter type the chosen overload takes first. None differs.
- **583 free-function modules agree**: for each call the frozen compiler
  records with a module-qualified symbol, the module sawc2's chosen target is
  declared in. None differs.
- **215 instantiations agree**: each generic call's type arguments, which in
  this build are `Vector`'s constructions and the generic helpers `put_at`
  and `trim_to`, and none differs.

The field types, signatures and Copy tiers of the section below were checked
again on the same run, and still agree (548, 1402 and 110, the counts grown
with the typecheck package).

A call is compared by file, line and callee name, as a multiset of what each
compiler records there, since the frozen compiler places a method call at its
`.` and sawc2 at its receiver. Translations, each applied by the script:

- a receiver's reference is read through, as sawc2's owner is the type a
  method is instantiated at;
- the frozen overload symbol `StringBuilder_append$OL$String` names the
  overload by its first parameter's type, which is compared with the first
  parameter of sawc2's target;
- the frozen module symbol `f$m$sawresolve_src_kinds` is compared with sawc2's
  target module, `sawresolve.src.kinds`; the entry module is unnamed in the
  frozen symbol and named `main` by sawc2;
- a construction's frozen type arguments, `Vector` with `Int,
  GlobalAllocator`, are compared with the arguments of the type sawc2
  instantiates the `init` at;
- the frozen compiler lowers a subscript into `[]` and `__lend_var_[]` calls
  and annotates `Vector.get` with its window's result type; neither is an
  instantiation, so both are left out;
- only a `let` or `var` statement's binding is compared, since the frozen
  compiler keeps an optional binding's type elsewhere.

## Signatures and Copy tiers (`frozen_check.py`)

Over the sawc2 build, the driver and the lex, parse, resolve and typecheck
packages, as they stood when U6b1 was written:

- **459 field types agree**, struct by struct, and none differs.
- **1009 signatures agree**, each free function's and method's parameter
  types and result type, by file, line and name, and none differs.
- **93 Copy tiers agree**, each struct's and enum's, and none differs. Every
  one is a concrete type: no struct or enum of `compiler/` is generic.

Three translations make the two comparable, and the script applies each:

- sawc2 spells a nominal type by its identity, module and path (design 144),
  and fills every defaulted argument; the frozen compiler renders the short
  name and the arguments as written. So the module qualifiers are dropped,
  and so is `GlobalAllocator`, `Vector`'s default and the only one the
  compiler's types leave out.
- An alias is transparent to sawc2, so `Byte` is `UInt8`; the frozen
  compiler keeps the alias's name. Two functions' results differ by that
  alone: `to_byte` in `compiler/lex/src/lib.saw` and `byte_of` in
  `compiler/parse/src/reader.saw`.
- The frozen compiler synthesizes a `deinit` method into each `NoCopy`
  conformance, twelve in the build. sawc2 records the same fact in the
  conformance table, `(deinit implicit)`, and adds no method.

The frozen tiers `free` and `implicit` are both Copy (design 219), and its
`abstract`, a type naming a parameter, would be compared with sawc2's rule
over the arguments; no type of the build needs it.
