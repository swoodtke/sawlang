# The one-time check against the frozen compiler

The record of `prelude_check.py`, run for SL-445 (SL:open-questions D12). The
frozen compiler's answers are checked and recorded here; they are never the
definition of what resolve must answer.

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

The check was run again for SL-447, when resolve began walking the signatures
of std and builtin modules, and for SL-448, when they began to be parsed as
interfaces; both times it found no unexplained difference.
