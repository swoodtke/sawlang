# Testing: `@test`

Part of the language lockdown that precedes the self-hosted compiler. This
describes the language that compiler will implement. It was decided in
conversation on Sep 24 2026, and every item here is ruled unless marked
otherwise.

## 1. Why tests live in the source

The self-hosted compiler is built test-first: focused tests that each take one
aspect of the design and cover every spelling of it. Tests sit next to the code
and the rules they pin, and one test mode serves everyone. The compiler's own
language suite and a user's library tests are run the same way.

## 2. The forms

`@test` is a compiler directive, like `@synthesize`. It changes whether a
declaration exists in a given build. Spelling it with `@` also leaves `test`
free as an ordinary name.

What follows `@test` decides the form:

```saw
@test "an expired token is refused" {           // a test case: runs
    let clock = FakeClock(now: 1000)
    …
}

@test(panics: "index.out-of-range") "indexing past the end panics" {
    let v: Vector<Int> = [1, 2, 3]              // passes only if the body panics,
    let x = v[10]                               // with that panic
}

@test(refuses: "move.use-after-move") "a moved value cannot be used again" {
    let x = Res()                               // passes only if the compiler
    let a = move x                              // refuses this block, and its
    let b = move x                              // first error has that ID
}

@test(warns: "default.ignored-on-store") "a pure store ignores the default" {
    var counts: Map<String, Int> = {:}          // passes only if the block compiles
    counts["a", default: 0] = 1                 // and emits that warning
}

@test func sample_doc() -> Document { … }       // a test-only declaration

@test {                                          // a group of test-only declarations
    struct FakeClock { now: Int }
    extension FakeClock: Clock { … }
    @test "a fake clock never advances" { … }   // cases may nest inside a group
}
```

- **A string makes a case.** Its body is statements, and it runs.
- **`{` makes a group.** Its body is declarations. Functions inside a group are
  helpers and are never run as tests.
- **A declaration makes that one declaration test-only:** `@test func`,
  `@test struct`, `@test extension`.

## 3. What each form does

| Form | Normal build | Test build |
|---|---|---|
| `@test "name" { … }` | typechecked, not emitted | compiled and run in its own process |
| `@test(panics: ID) "name" { … }` | typechecked, not emitted | passes only if the body panics with that panic |
| `@test(refuses: ID) "name" { … }` | skipped; only its braces are matched | checked on its own; passes only if its first error has that ID |
| `@test(warns: ID) "name" { … }` | typechecked, not emitted, like an ordinary case (no rot; warnings are off by default) | checked on its own with the category enabled; passes only if it compiles and emits that warning |
| `@test(warns: none) "name" { … }` | typechecked, not emitted | passes only if it compiles with every category enabled and emits no warning |
| `@test func` / `@test { … }` | typechecked, not emitted | compiled; visible only to test code |

## 4. Rules

- **Placement and access.** `@test` declarations sit at top level in any file,
  or inside an `@test { … }` group, and can reach their module's private
  members, so white-box testing works.
- **A case body is driven like `main`.** It may suspend, spawn tasks and use
  `TaskGroup`. In a test build, the runner's entry drives each case, and a
  file's own `main` is not the entry.
- **One key per diagnostic** (Air t12). A refusal's ID, a panic's ID and a
  warning's ID are the rule's stable name (§6): `@test(refuses: "borrow.root-charge")`.
  There is no second catalog of `E_…` codes. The error text shows the name, as
  Rust shows `E0499`. The same key serves `refuses:`, `panics:`, `warns:` and
  `// rule:` citations.
- **A key is written as a string literal** (Air t16):
  `@test(refuses: "move.use-after-move")`. Rule names are dotted and
  hyphenated, so a bare `move.use-after-move` would lex as a keyword and
  subtractions. The optional `text:` and `at:` arguments are separate labelled
  slots, so the parser always knows which one it is reading, and a text alone
  is still not accepted.
- **`panics:` names which panic** (Air t10; Ruled). A bare `@test(panics)`
  would pass on an unrelated panic, such as a bounds check in the setup or a
  `try!` on a fixture, and silently stop testing its subject. So the form takes
  the panic's key, and optionally `at:` to pin the line, as refusals do:
  - a compiler-inserted check (bounds, overflow, shift, unwrapping `None`,
    `try!`) has an ID from the same rule-named catalog;
  - a user `panic("…")` has one ID of its own, `panic.explicit`. The optional
    `text:` slot, the same slot `refuses:` has, checks its message:
    `@test(panics: "panic.explicit", text: "queue drained") "…" { … }`. So
    every panic test names an ID, and a key is never mistaken for a message
    (SL:grammar, SL-400 c6 Q16).

  The structured panic record already carries `panic at FILE:LINE: message`
  (design 122), so matching costs nothing.
- **Scope.** A test sees its enclosing file's scope: its imports and every
  declaration in it. There is nothing to re-import.
  - **Test-only imports** (Ruled): an import only tests need is written
    `@test import std.fs`. Its names are visible only to test code, in both
    normal and test builds. It never enters the production namespace or the
    emitted dependency set, so production code never gains that dependency or
    those names. It is the same rule as test-only declarations.
  - **Consistency with no-rot** (codex t7): a normal build still typechecks
    in-file tests, so it must still *resolve* their test imports. For std
    modules that costs nothing. For a package, Blade must have the test
    dependency available (a dev-dependency) to typecheck, even though nothing is
    linked against it. Skipping test dependencies entirely in normal builds
    would need an explicit exception to no-rot. That is not proposed, and the
    bootstrap's Stage 0 remains the only source set that omits test code.
  - A sidecar sees its module's scope exactly as an `@test { … }` group in the
    implementation file would, imports included.
- **Runtime state is not shared.** Compile-time scope is shared, but each test
  runs in its own process, so statics start fresh for every test, and no test
  can leave state behind that changes another's result.
- **Test sidecars** (Ruled: "parser.test.saw tests parser.saw like it was
  @test { .. } defined in the parser.saw file"). A file `parser.test.saw` beside
  `parser.saw` means exactly what an `@test { … }` group at the end of
  `parser.saw` would mean:
  - it is part of module `parser`, with white-box access to its private members
    and the implementation file's imports;
  - everything in it is test-only: typechecked in every build (no rot) and
    emitted only in test builds;
  - it makes nothing public and does not weaken production visibility;
  - it may add imports of its own. Since everything in a sidecar is test-only,
    they are test-only imports, exactly as `@test import` is in the
    implementation file.

  The only difference is where the text lives. That matters for the
  self-hosted compiler, whose implementation files must stay in the subset the
  frozen compiler parses (no `@test`). The bootstrap's Stage 0 source set
  excludes `*.test.saw`, and Stage 1 onward includes it. (An importing test
  module would not do: it gets no private access.)
- **No rot.** Ordinary cases and test-only declarations are typechecked in every
  build, whether they are in the implementation file or its test sidecar (above),
  so they cannot silently decay. They are emitted only in test builds. The only
  source set that omits sidecars is the bootstrap's Stage 0, which is a
  bootstrap step, not an ordinary build.
- **Test-only means test-only.** A reference to a test-only declaration from
  ordinary code is a compile error: "`FakeClock` exists only in test builds".
  This keeps a fake from leaking into production code, such as a counting
  allocator in a real path or a fixed clock in a kernel.
- **Test code cannot change what production code means**, in either build
  mode. Name visibility alone is not enough, because a test-only extension can
  supply a conformance or an overload without production code ever naming it.
  So:
  - production code is checked as if no test-only declaration existed: its
    overload resolution, generic-bound satisfaction and copy-tier
    classification never see test-only conformances;
  - a test may instantiate production generics with test-only types (a
    `FakeClock` passed to `func f<T: Clock>`), and that instantiation belongs to
    the test build;
  - a test-only conformance that overlaps a production conformance is refused;
  - a test-only copy-family conformance (`Copy`, `ExplicitCopy`, `NoCopy`) on a
    production type is refused outright (Air t15). Every type already has a
    tier, so one would give a single type two tiers in one binary once a value
    crossed from test code into a production generic.
- **Each test runs in its own process.** A Saw panic aborts the process (there
  is no unwinding), so isolation is what lets one failing test fail alone.
  Tests run in parallel, and `@test(panics)` works because of it.
- **One compile per file, one process per case** (Ruled). Compiling is the
  expensive part, not starting processes. The Python compiler spends about
  2.5 s per compile before reading the test at all, and a compiled case runs in
  about 3 ms. So related tests live together in large aspect files, each file
  compiles once into one test binary, and the runner starts that binary once per
  case:
  - `--list` prints the binary's case names, and `--case <name>` runs exactly
    one. The runner spawns the cases in parallel, with a timeout per case;
  - refusal cases need no binary. The same compile checks each one as its own
    unit and reports its verdict;
  - **a case that fails to compile fails alone.** Each case is its own checking
    unit, so the compiler reports that case and still builds the rest of the
    file (SL:architecture §3.0: a unit with errors is poisoned and skipped);
  - **the test compile writes a manifest, and the runner reads it** (codex t8).
    `--list` on the binary cannot be the inventory, since it omits refusal cases
    and cases that failed to compile. The manifest accounts for every case the
    compile discovered, each with exactly one outcome:
    - *runnable*, naming the binary;
    - *refusal*, with its verdict and the diagnostic it produced;
    - *compile failure*, with its diagnostics;
    - *blocked*, naming the failing shared declaration it depends on. A bad
      helper, import or fixture is an error in *its* unit, and every case that
      uses it is blocked by name, never silently dropped.

    A parse failure that prevents discovery is a *build failure* for the whole
    file, never an empty, passing suite. The runner runs the runnable cases
    whether or not others failed, and its aggregate result fails if any case
    failed or was blocked. It reads the manifest, not the compiler's exit status
    alone, which cannot express a partial build. A compiler crash or timeout, or
    a missing or incomplete manifest, is still a build failure for the file,
    even if some output exists. A file with no runnable cases needs no binary;
  - **the manifest belongs to one invocation** (Air t13). A compile that dies
    before writing would otherwise leave the previous run's complete manifest
    and binary behind. So the runner deletes both before compiling and passes a
    fresh token, which the manifest echoes. A manifest without the current
    token is a build failure. Today's test runner needed the same guard, and
    design 220 gives every invocation its own directory for this reason;
  - setup for a group runs inside each case's process. A fixture is a value, and
    its deinit is the teardown. Sharing an expensive setup across cases (for
    example by forking from a post-setup parent) can be added later if
    measurement shows the need.
- **A panic test needs evidence of a Saw panic, not just an abort.** An
  allocator assertion or an unrelated native crash can end a process the same
  way. So the test runtime's panic handler reports a structured record naming
  the case and the panic, and `@test(panics: …)` passes only on that record,
  from that case, naming the expected panic.
  These all FAIL a panic test: a crash, a timeout, any other abort, and a
  failure before the case starts. Otherwise a regression that turns a checked
  panic into a native crash would pass silently. Likewise, a compiler crash or
  timeout never satisfies `@test(refuses:)`: only a real diagnostic with the
  expected ID does.
- **One test mode.** `sawc --test <paths>` and `blade test` run the same mode.
  "Compiler testing" is that mode pointed at the language's own test files
  (e.g. `tests/lang/`). Library authors get tests that prove misuse is
  refused, which Rust needs a separate tool (`trybuild`) for.
- **Test code is checked under the test build's profile** (Ruled). A `@test`
  inside a module built `--freestanding --no-hidden-alloc` is checked as hosted
  test code, so it may print and interpolate. Freestanding testing is a
  separate suite: the sawos gate under QEMU is the model. A fake `hal` inside an
  `@test { … }` group still cannot leak into the kernel, because test-only
  declarations are invisible to ordinary code.
  - **Consequences** (Air t14; Ruled). *Running* a hosted test of a
    freestanding module compiles the module's production code hosted too. So a
    module keeps tests in-file only if its production code is hosted-runnable
    along the paths its tests exercise (Air t16). Compiling hosted is rarely
    the limit: `unsafe static var` slabs, `@section` and addresses held as
    `UInt` all compile. What cannot run on a host is dereferencing an MMIO or
    physical address, or a real `hal`. Logic that needs those is tested in the
    QEMU suite.
  - For the same reason, a normal freestanding build checks such a module
    twice: its production code for the real target (a 32-bit `Int` on riscv32,
    for example), and its production code plus tests for the host test profile.
    Literal ranges and constant folding are therefore checked on both targets,
    and a mismatch between the two is a real portability error to report.
- **Stress tests are separate** (Ruled). In-file tests test *functionality*.
  Stress and soak harnesses test *safety guarantees* under load, such as
  oversubscription races, and stay separate tools (parksoak is the model).
  SL-353's lost wake stalled 88 of 640 oversubscribed runs and never appeared in
  a serial one, which no single `@test` process can see.

## 5. Refusal tests (`@test(refuses: …)`)

- A refusing block is checked **on its own, as a unit**, like a small inline
  module. It may contain declarations, because many refusals are about
  declarations:
  ```saw
  @test(refuses: "field.no-reference") "a struct field cannot hold a reference" {
      struct Holder { r: &Int }
  }
  ```
- Its errors are expected and contained. They never fail the build or leak into
  the rest of the file.
- **It leaves no semantic state behind.** A refusing unit is checked against a
  copy of the environment it can see. Declarations or conformances it registers
  before failing are invisible to sibling units and to production code, so the
  order of cases can never change a result.
- **Matching is on a stable diagnostic ID** (Ruled: yes, provided the expected
  errors form a finite, enumerable set, which they do). The ID is the rule's
  name (§4, "One key per diagnostic"), for example
  `@test(refuses: "closure.exclusive-capture") "…" { … }`. **The ID is required**
  (Air t9). An optional `text:` argument adds a substring check on the message.
  A text alone is not accepted, since it would bring back the churn that IDs
  remove. The block must produce errors, and its *first* error must carry that
  ID, so a block refused for an unrelated reason (a typo) fails the test instead
  of passing. An optional `at:` argument pins the line within the block.
  - **Why IDs:** diagnostics get reworded often (SL-345's hint changed twice in
    one review), and each rewording would churn every test pinning the phrase.
    An ID also gives each spec rule a citable name.
  - **The catalog is finite.** Every refusal is a site in the compiler. Today's
    Python compiler has 22 coarse `ErrorKind`s over about 780 refusal sites
    (about 700 in the typechecker, 75 in the parser), which is countable but
    too fine-grained to reuse directly. In the new compiler, IDs are defined
    with the spec rules: each rule that refuses something names its ID, and the
    catalog is exactly the set of refusing rules.
- **What cannot live in a file**, and so stays as corpus files with an
  EXPECT-ERROR header (which also names the diagnostic ID), one refusal per
  file:
  - refusals the token-level brace match cannot delimit (Air t15): lexer errors,
    such as an unterminated string or comment, and unbalanced braces. Any other
    parse error sits in a brace-balanced body, so it can be tested in-file,
    because a test build parses the block as its own unit;
  - multi-file refusals: imports and module layout.
- **Warnings are tested in-file too** (Air t11; Ruled), with `warns:` (§3).
  Unlike a refusal, a `warns:` case is valid code, so a normal build
  typechecks it like an ordinary case (no rot), and adds no noise, since
  warnings are off by default. In a test build it is checked as a unit with its
  category enabled, and passes only if the block compiles and emits that
  warning (Air t16). `warns: none` passes only if the block compiles with every category
  enabled and emits nothing, since a warning that should not fire is the usual
  regression. The rules whose whole behaviour is a warning, such as
  SL:borrowing §5.4's ignored default and §8a's static-root warning, get their
  tests this way.
- **Compiler constraint:** diagnostics are collected per checking unit, never
  thrown in a way that aborts compilation. The new compiler adopts this from
  the start.

## 6. How the test-first suite is organised (Ruled)

- Tests are grouped by **aspect**: one aspect per file, each going deep on every
  spelling of that aspect in every position.
- Each test names the spec rule it pins, so every rule can be traced to its
  tests and every test to its rule. **Rules have stable names** (Ruled), such as
  `borrow.root-charge` or `copy-tier.explicit-transfer`, anchored in the spec
  text. Inserting a rule never renumbers the others, and a test cites one as
  `// rule: borrow.root-charge`. A lane checks both directions: every rule has a
  test, and every cited rule exists.
- **The rule inventory is the coverage target.** Every rule in the spec and the
  lockdown docs gets its name. The existing tests (`examples/`, the conformance
  suite, the spec's checked examples) are then mapped onto the inventory, and
  the gaps are filled, one aspect at a time. A test states the intended
  behaviour, whether or not the frozen compiler passes it.
- The spec's own `saw-error` examples, checked by docverify, are the canonical
  refusal for each rule. The in-file and corpus tests are the full matrix.
- **Two corpora, paired by file** (Ruled: "the corpus/ for the tests is fine";
  SL:architecture §5). The existing `examples/` corpus, about 2,700 programs
  with EXPECT directives, stays unchanged as the frozen compiler's corpus. The
  new compiler's measure of progress is its migrated copy in `tests/corpus/`,
  in the new spellings. The behavioural differential runs the frozen compiler
  on each original and the new compiler on its migration, and compares them.
