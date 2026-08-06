# Design 148 — const generics + repeat literals (DF-137a/b)

STATUS: APPROVED (user, Aug 5 — "relatively clean and nice usability
wins"). Slots PAIRED WITH 138 after 147 and 135 (disjoint trees: 138 is
README-only). Closes DF-137a and DF-137b.

## Unit A — the bound diagnostic (the DF-137a bug half)

TODAY `struct FixedBuf<N: Int>` PARSES AND COMPILES its declaration —
a type-param bound naming a non-trait is never checked — then fails at
every use with "undefined variable". Silent-wrong-answer shape. After
unit C lands, `<N: Int>` gets a teaching error with a fixit pointing at
the const spelling (`<const N: Int>`); any other non-trait bound
(`<T: String>`) errors as "not a trait". This unit lands FIRST so the
diagnostic exists even if later units slip.

## Unit B — repeat literals (DF-137b)

`[v; N]` — an array literal of N copies of v. Parser (the form is
unambiguous inside `[ ]`), typechecker (v's type = element type; N a
compile-time constant — INCLUDING a const generic param from unit C),
codegen (memset for all-zero bytes, splat-loop otherwise; element type
must be trivially copyable or ImplicitCopy — an ExplicitCopy/NoCopy
repeat is a teaching error naming the policy). `[0; 256]` finally
spells a zero stack buffer. Statics accept it as const-init.

## Unit C — const generics (DF-137a proper)

`struct FixedBuf<const N: Int> { data: [UInt8; N] }`, `FixedBuf<256>`.
The `const` keyword in the parameter position keeps value params
visually distinct from trait-bounded type params. v1 scope, kept
deliberately tight:
- Value parameters of type Int/UInt (fixed-width later if wanted).
- Usable wherever a compile-time constant is: `[T; N]` lengths,
  `static_assert`, sizeof arithmetic, repeat literal counts, plain
  expression use (N as an Int value in the body).
- Const ARITHMETIC in instantiation position: v1 accepts literals,
  const params, and +/-/* of those (the static_assert evaluator's
  existing const-eval discipline — reuse it, do not grow a second
  evaluator).
- Monomorphization keys extend to carry values (design 144's
  module-qualified identity work is adjacent — coordinate the key shape
  so the two changes compose; 144 runs BEFORE this in the queue).
- Explicit instantiation only in v1: NO inference of N from argument
  shapes except the one obvious case — a `[T; N]` argument binds N
  (the design-93 solver already unifies array lengths; verify).
- Default values compose with design 108's default-value machinery
  (`<const N: Int = 256>`).
- Generic enums/structs/functions all accept const params; extensions
  on a const-generic type work like any generic extension.
FOLLOW-UPS explicitly out: const params of user types, where-clauses /
comparisons over N (`N > 0` — use static_assert in the body), variadic
shapes. The FixedStringBuilder<N> shape from design 137 becomes the
acceptance test: build it in std as `FixedBuf`-backed and the 137
compiler-alloca'd scratch can migrate to it in a later cleanup.

## Gates
Per-unit commits, suite green each; final battery incl. irdet-all.
Spec (generics + literals sections) + skill (the fixed-buffer idiom;
the repeat literal) + README if examples benefit. Tracker: DF-137a,
DF-137b closed.
