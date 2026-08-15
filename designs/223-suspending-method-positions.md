# Design 223 — suspending-method positions: one classifier, three-valued, never silent

**Status: AUTHORED Aug 14 from the DF-218k/l/m obligation-4 sweep
(probes + full matrix: `.build/scratch/sweep218klm/`, GITIGNORED — this
brief carries what the fix needs; the matrix below IS the test plan).
FULLY RULED (user, Aug 14 night): question 1 = work-where-the-mechanism-
exists (existential dispatch refuses cleanly, own DF); question 2 = the
closure-body axis joins the DF-219b family brief, 223 does not touch it.
Dispatched.**

## The finding, in one sentence

The coroutine transform's call-site classifier answers a two-valued
question with a name-keyed lookup that cannot name an enum receiver, a
generic receiver, or a generic method — and all seven of its consumers,
including both rejectors, read its `None` as "not a suspending call"
rather than "I cannot express this", so unsupported positions degrade to
PLAIN SYNC CALLS instead of errors. Seven probed cells compile, run,
produce correct values, and never suspend. The typechecker's effect graph
is EXACT throughout (it refuses `sync` callers of these very methods by
name and line); only the transform disagrees with it.

## The mechanisms (three, two inseparable)

- **M1 — `_method_call_owner` (coro_transform.py:1530-1557).** The
  receiver-typed branch reads only `struct_name` (an enum carries
  `enum_name`, types.py:171 — falls through), explicitly excludes generic
  receivers (`type_args` → None), and its docstring's promise that "the
  call site is rejected cleanly downstream" is FALSE — both rejectors
  (:4218-4229, :4268-4285) consume the same None. Seven consumers:
  `_classify_method_call` :4092, `_method_call_suspends` :4194,
  `_suspending_method_call` :4213, the two rejectors, the :7778 chain
  lowering, `_scan_method_callees` :8178. The enum STATIC path works
  (reads the bare `static_receiver` name), proving the rest of the
  pipeline handles enums; the ROOT position works for generics (the
  `gsm` table :8511-8541 computes concrete per-instantiation receivers),
  proving the keying exists.
- **M2 — the closure walk's definition-side skip (:8313-8315)** keys on
  the METHOD/EXTENSION's `type_params` while M1 keys on the RECEIVER;
  the misalignment is why one hole shows four different symptoms (ICE /
  silent sync / raw KeyError / wrong-shaped diagnostic). M1 and M2
  CANNOT be fixed apart — fixing M1 alone converts four silent-sync
  cells into KeyErrors.
- **M3 — the strip (:8592-8593), = DF-218k, separable but same
  landing.** `ext.methods` drops the transformed method; the
  post-transform re-typecheck (sawc.py:1488-1498 →
  registration.py:2810) then reports the CONFORMANCE as unimplemented.
  Entry-module-only (`_entry_ext_ids`); cross-module conformances work
  (probe-proven, frame built).

## The fix (obligation-1 funnel)

**Unit 1 — the three-valued classifier.** Replace `_method_call_owner`
with `_suspending_method_target(mc) -> EMBED(frame_key) |
UNSUPPORTED(reason, line) | NOT_SUSPENDING`, docstring naming all seven
entry points, with THE invariant: **UNSUPPORTED raises a clean
diagnostic; it never degrades to a plain call.** Receiver keying reuses
what the root position already has — the `gsm` table's concrete
instantiation key, flowing through `_method_frame_key` (:1566, already
the documented single frame-identity spot). `enum_name` is read beside
`struct_name`. M2's skip (:8313) aligns to the same three-valued answer
in the same commit.

**Unit 2 — the strip funnel (M3/DF-218k).** `_strip_driven_method(ext,
mast)` refuses to remove a method the extension's conformances require —
or leaves a forwarding shim — so the post-transform re-typecheck stops
being the only thing that notices.

**Cell policy (decided, pending the user's confirmation below): a cell
becomes WORKING where the concrete mechanism already exists at another
position, and a CLEAN REFUSAL citing its DF where it does not.**
Working: enum instance methods (E, E4 — the static path proves the
pipeline), generic struct methods embedded (F, F3, F4, F5 — the root
path proves the keying), generic methods on concrete structs (G),
conformance methods entry-module (B, B4, L2 — cross-module proves it).
Clean refusal: existential dispatch of a suspending conformance body
(C2, C3 — dynamic dispatch has no compile-time frame identity; new
design owed, DF filed). Blast radius of the flips: ZERO tracked code
uses any affected embedded shape (sweep §5 — every existing
generic/enum coro test drives from the ROOT position, which is exactly
why these survived).

**Unit 3 — the diagnostic warts inside the family.** Cell G's raw
Python `KeyError` (no ICE breadcrumb, no anchor) and cell I2's message
blaming `if let`/`guard let` for a closure literal; the :0:0 unanchored
existential refusal (C) gets an anchor.

## The test plan — the matrix, row by row, THREE properties each

(1) compiles; (2) `__Frame_<owner>_<method>` present in `--emit-ir`;
(3) two spawned tasks interleave `A1 B1 A2 B2`. Property (3) is the one
that catches silent sync — the existing generic/enum coro tests assert
output values from the root position and would pass on every broken
cell. Rows (verdicts = current main, the fix's targets in brackets):

| cell | position | today | target |
|---|---|---|---|
| A/H1/D/J/E3/F2/H2/B2/B3/B5/E2 | controls (plain, cross-module, default body, statics, roots, fences) | OK | stay OK |
| B, B4, L2 | conformance entry-module (struct + enum, embedded + root) | bogus refusal | WORK |
| E, E4 | enum instance (entry ICE / cross-module SILENT) | broken | WORK |
| F, F3, F4, F5 | generic struct embedded (incl. &var self, static, cross-module) | SILENT SYNC | WORK |
| F6 | generic + self-capturing closure | ICE | WORK (rides F) |
| G | generic method on concrete struct | raw KeyError | WORK |
| C2, C3 | existential dispatch, suspending impl | SILENT SYNC | CLEAN REFUSAL (DF filed) |
| C | &any param in suspending fn | unanchored refusal | anchored |
| K | std name collision forces a frame on sync user code | over-inclusion | resolved by the typed key (falsifies DF-206d's "not live") |

Conformance rows: the silent-sync rows are safety-surface rows
(obligation 3 — the cooperative contract is a language guarantee);
written first as cited pins.

## Adjacent findings the sweep proved, filed separately (NOT this brief)

- **DF-218o** — qualified `task.yield_now()` inside a GENERIC extension
  method is refused as a bare-intrinsic call; the qualifier is lost
  across the monomorphized clone. Concrete twin works.
- **DF-218p** — a cross-module qualified GENERIC STRUCT LITERAL
  (`dep.Pair<String>(a: "x")`) does not substitute its type argument;
  plain typechecker/mono bug, no coroutine involved.
- **DF-218q** — `&p` to an `&any Trait` parameter inside a SPAWNED body
  is refused UNANCHORED (:0:0) with nothing suspending; the direct call
  twin compiles.
- The closure-body axis (cells I/I3/I4): a suspension inside a closure
  literal's body is silently sync — DOCUMENTED (LANGUAGE_SPEC:5611) but
  silent, contradicting designs 96/101/104's "never silently block".
  OPEN QUESTION 2 below.

## Open questions (user)

1. **Confirm the cell policy** — work-where-the-mechanism-exists,
   clean-refusal-where-it-doesn't (existential dispatch). The
   alternative (refuse everything, support later) is smaller but leaves
   the root/embedded asymmetry in the language.
2. **The closure-body axis**: ride this brief as a clean refusal (a
   suspension in an un-driven closure body becomes an error naming the
   design), stay documented-silent (today's state), or take its own
   brief (the DF-219b closure-body suspend-position family already in
   the queue is the natural home).
