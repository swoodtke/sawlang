# Design Brief 12 — Tech-debt XFAIL suite

**Purpose:** encode every *outstanding, harness-expressible correctness issue*
as an XFAIL test, so the suite is the tech-debt ledger: yellow = known debt,
XPASS = a fix landed and the marker must come off. Sources: the "Known
follow-ups" list in `todo_jul26.md` and the agent reports referenced there
(briefs 02, 04, 10, 11 in `designs/`).
**Scope:** tests only — NO compiler/stdlib changes. Method: brief 01's
verify-twice protocol (prove each test red without the marker, then land it
as `// XFAIL: <ledger item>` with correct-behavior EXPECT directives —
re-read TESTING.md).
**Exit criteria:** full suite green (new tests yellow, zero red, zero XPASS);
report classifies every ledger item as tested / not-expressible / not-reproducible.

## Tests to write (verify each reproduces first; drop with justification if not)

1. **Use-after-move via call argument** (use-after-move dataflow gap, brief
   03 report): `consume(move v)` then `v.push(...)` — move through a call arg
   isn't recorded, so the use compiles. `// EXPECT: error` (use-after-move
   diagnostic), XFAIL. Also a `move` in a struct-field init followed by use,
   if it reproduces. Do NOT write branch-merge cases (semantics undecided).

2. **Generic-struct deinit skipped — conformance-name mismatch** (brief 04
   report, resources.py `_get_type_name_for_conformance` vs canonical
   mangled method names): a generic struct (e.g. `Box<T>`) with
   `extension Box<T>: Deinit` printing on deinit; instantiate, let it go out
   of scope. Expected output includes the deinit print; currently the cleanup
   lookup misses. `// EXPECT: success` + output, XFAIL. If it turns out
   deinit DOES fire (the mismatch may only affect one lookup path), probe the
   copy()-lookup path too, and report precisely which path is broken.

3. **Field assignment through `&var` struct param** (brief 10 report):
   `func set(r: &var Box) { r.field = 5 }` — codegen raises "Cannot determine
   struct type for field assignment". `// EXPECT: success` + output, XFAIL.

4. **Exclusivity misses immutable-borrow receivers** (brief 10 report): a
   method taking `&self`-style borrowed receiver called as
   `x.read(&var x)` — mutable arg overlapping the borrowed receiver should
   be an exclusivity error but is accepted. First verify the receiver truly
   is a borrow (not a by-value copy — if receivers are copies, the program
   is well-defined and there is NO bug: report that instead of forcing a
   test). `// EXPECT: error`, XFAIL only if genuinely unsound.

5. **`Vector<T>` elements not deinit'd** (brief 11 report): `Vector<R>`
   where `R` is a Deinit-printing resource; push elements, drop the vector;
   element deinits must print. `// EXPECT: success` + prints, XFAIL.
   (Vector's own Deinit frees the buffer; the ELEMENTS are the gap.)

6. **Method-result temporaries never cleaned** (brief 11 report):
   `makeResource().use()` — the temporary receiver of a Deinit-printing type
   must be destroyed after the statement; currently never is.
   `// EXPECT: success` + deinit print in output, XFAIL. Similarly a
   temporary passed as an argument if it reproduces distinctly.

7. **Struct String/Deinit field cleanup exemption** (brief 11 report:
   String fields are exempted from implicit-copy containment and structs
   without declared Deinit don't release fields): if expressible with an
   observable (a struct holding a Deinit-printing type WITHOUT declaring
   anything — check whether containment rules force a declaration; if they
   do, this case can't exist and only the String variant remains, which has
   no observable — then classify as not-expressible and move on).

8. **Nested no-else `if` as if-let branch tail** (brief 11 report): the
   undominated-SSA-store repro with `Int?` — a compiler crash on a valid
   program. `// EXPECT: success` + output, XFAIL (crash counts as failure).

9. **Generic-body deferred checks** (brief 02 report, documented looseness):
   (a) unused generic whose body calls a method not guaranteed by `T`'s
   bounds; (b) unused generic whose body returns the wrong concrete type.
   Both compile clean today; correct behavior is a compile error.
   `// EXPECT: error`, XFAIL. Keep to clearly-wrong cases (returning `Bool`
   from `-> Int`), nothing that abstract-checking could legitimately defer.

10. **Module symbol collision resolved first-wins silently** (structural
    issue, `namespace.py merge_into`): if the module-test layout under
    `examples/` supports it cheaply (model on existing module tests), two
    modules exporting the same name, importer uses it — correct behavior is
    an ambiguity/collision error; today it silently picks one.
    `// EXPECT: error`, XFAIL. Skip with a note if module test plumbing
    makes this disproportionate.

## Explicitly NOT tests (record in report, no test)
- `--emit-ir` builtins (no CLI-flag directives in the harness).
- `noalias` on `&var` params (optimization; no observable).
- Vector<File>.copy() traceback cosmetics (error already asserted by an
  existing test; traceback-vs-diagnostic isn't expressible).
- Call-site `&x` vs `&var` param validation (design decision pending —
  flag, don't presuppose).
- Raw String-field leaks with no printable observable.

## Report back
Per ledger item: tested (filename + how it fails today) / not-reproducible
(what you tried) / not-expressible (why). Any NEW correctness issues you
stumbled on while probing — report them; add an XFAIL test only if the
expected behavior is unambiguous. Non-allowlisted commands used (ideally
none).
