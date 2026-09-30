# The one-time checks against the frozen compiler

The record of `frozen_check.py` and `prelude_check.py`, run once for SL-445
(SL:open-questions D12). The frozen compiler's answers are checked and
recorded here; they are never the definition of what resolve must answer.

## Call heads and import bindings (`frozen_check.py`)

Over the sawc2 build, the driver and the lex, parse and resolve packages, as
they stood when SL-445 was revised:

- **6323 call heads agree**, line by line, and no line differs.
- **248 selective import bindings agree** on the kind of declaration each name
  binds.

Two translations make the two comparable, and the script applies both. The
frozen compiler rewrites a subscript into a call of its accessor (`[]`,
`__lend_var_[]`), which is no call in the source, so those are left out. Its
parser guesses that `name(label: ...)` builds a struct and its typechecker
turns the guess back into a call where it was one (`as_function_call`); the
call's final reading is what is compared.

## The tables (`prelude_check.py`)

- The std module table lists exactly the files under `sawc/std`.
- No synthetic builtin declaration is declared by `builtin.saw` or std.
- Every name the frozen prelude makes visible that a curated core would keep
  is in the prelude table, from the module the frozen compiler says declares
  it. The frozen prelude also holds 145 runtime and compiler-internal names
  (`__` first), 25 extern C declarations std makes for itself, and one std
  file's private function (`to_c_char`), which its exclusion list lets
  through and an inclusion list leaves out.
- The prelude table's names the frozen prelude does not list are the ones its
  typechecker knows without a declaration: the primitive types, `Void`,
  `Never`, `Optional`, the pointer types and the builtin functions.
