# M17: shared-subset compiler agreement (SL-260)

M16 established unchanged-lexer execution. This milestone establishes an
auditable compiler-agreement guard and fixes the known String receiver access
gap. The Python compiler is a comparison oracle, not authority to reproduce
its bugs. No production compiler changes belong in this patch.

## String receiver borrowing

Every String intrinsic invoked on a named place must register a shared borrow
of that place's root before evaluating its arguments. Keep it active through
the entire intrinsic call and release it afterward. Use the same root-based
exclusivity checks as ordinary methods/references. A shared intrinsic receiver
has already been staged as a value, so permit that read of a pending assignment
destination (`text = text.substring(...)`). Keep pending-write checks on explicit
argument borrows, and keep the active receiver borrow through all arguments so
this exception cannot permit an argument-side mutation. Cover local
Strings, String fields of named records, reference parameters, nested fields,
and parenthesized named places. Do not grant a bypass by reading/snapshotting
the receiver into an internal temporary before the borrow is registered.

Retain source-place provenance through the expression forms that still denote
that place, even where the implementation stages a retained copy. Do not
propagate root provenance into genuinely fresh results (calls, substring result,
value-control result, constructors). A temporary String has no independently
mutable source slot to protect; methods on it remain supported. String copies
and runtime retain/release behavior remain intact; this is a frontend access
check, not a new runtime representation or general borrowing-place mechanism.

Use one intrinsic wrapper/check path so to_uint, equals, substring, byte_at,
len and is_empty cannot diverge in their receiver rules. A chain releases one
call's borrow before proceeding to the next fresh result. Overlap diagnostics
must be located. Error paths may abort compilation normally.

Convert the existing strings/receiver_snapshot_order and
unsigned_parse/receiver_snapshot programs into rejection cases without erasing
the repros. Remove the old SL-260 known acceptance divergence. Add focused
positive controls for fresh/chained results, independent mutation, shared
access and once-only argument evaluation; rejection controls cover mutable
arguments in each argument-taking intrinsic, fields/references/parentheses,
and later arguments. Include self-assignment with nested shared reads and its
mutable-argument rejection counterpart. Preserve conservative record-root overlap
as documented. The unchanged lexer requires this self-assignment form.

## Complete classification of registered fixtures

Create a versioned explicit manifest for every RunCase and RejectCase registered
by test_minivm.py. A new or removed fixture must fail manifest validation until
its classification is updated. Engine-only budget/depth tests remain in the
ordinary regression gate and are reported separately. No default silent skip.

Each row is one of:

* agreement: both compilers must agree on acceptance; accepted programs must
  produce the registered fixed output/status, including VM/native prototype
  checks. Ordinary diagnostic wording need not match, but crashes, internal
  errors and timeouts never count as rejection.
* known difference: issue-linked, explicit expected compiler outcomes and
  diagnostic/output evidence. Unexpected agreement is a gate failure requiring
  ledger reconciliation, not an automatic pass. Keep prototype fixes distinct
  from production findings; do not file known prototype shortcuts as sawc bugs.
  This includes accepted programs with different runtime tuples. A filed Python
  internal compiler error uses a separate `internal_error` outcome, never a
  language rejection: require exit 1, the compiler's internal-error diagnostic
  shape and case-specific evidence. Report these known internal errors separately.
  An arbitrary error, traceback, signal or timeout cannot satisfy that outcome.
* subset exclusion: a concrete reason tied to COMPATIBILITY.md or a milestone
  contract. Prototype-specific runtime trap formatting may be outside exact
  output comparison, but ordinary valid shared arithmetic is not excluded just
  because an unrelated case in its section uses a shortcut.

Prefer broad agreement coverage across every implemented milestone, not just
the existing compare_sawc flags. Audit actual fixture source. Do not label
everything unmarked as excluded with a generic reason. Preserve same-source
comparisons; do not rewrite fixture programs to obtain agreement. Existing
known Python bugs such as SL-284/285 use their own issue-linked evidence if
included, or explicit exclusion rationale pending a dedicated regression.

Add focused shadowing evidence and an issue-linked known row if the gap remains;
do not silently bless prototype shadowing as full Saw behavior. The initial
M5 literal-inference difference and executable bare-brace blocks also need
explicit accounting where present in the corpus. Issues may remain open after
this guard lands; the guard's completeness is not the elimination of every
future language feature or known difference.

## Gate behavior and review

Provide a reproducible CLI with section/filter options, bounded subprocess
execution, complete failure artifacts and concise summaries of agreement,
known and excluded counts. Print PASS only after every required engine actually
ran and matched. Validate manifest identity/schema before expensive compiles.
Compile errors must be clean diagnostics, not arbitrary exit 1. Known rows need
stable diagnostic substrings and expected outcomes, never "any error is fine".
Check that referenced local issue states are not closed when claiming an active
known difference; missing tracker state is reported explicitly, never invented.

All prior prototype tests and the 39-input unchanged-lexer gate remain green
after the receiver change. Run the new agreement guard over its entire declared
corpus. File new production findings, with minimized evidence, before registering
exceptions. Update README and COMPATIBILITY as differences are fixed/discovered.

Sol frontend owns frontend.saw, focused fixtures and their test_minivm registry
entries. Sol harness owns the new differential script/manifest and its meaningful
validator/known-outcome tests. Parent authors the design, reviews classification
and changes, owns tracker findings and docs, integrates and submits.
